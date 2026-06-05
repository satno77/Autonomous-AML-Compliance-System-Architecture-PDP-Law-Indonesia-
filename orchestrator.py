import os
import sqlite3
import random
import json
from datetime import datetime, timedelta
from typing import TypedDict, List
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from langchain_core.tools import create_retriever_tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent 
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from fpdf import FPDF


#1 CONFIGURATION & LOCAL LLM SETUP

llm = ChatOpenAI(
    base_url="http://localhost:11434/v1", 
    api_key="ollama", 
    model="llama3.1", 
    temperature=0.0 
)


#2  DATA SETUP: JUDI ONLINE MULE ACCOUNTS

DB_FILE = "aml_transactions.db"

def setup_sqlite_database():
    print("Initializing SQLite Database...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('DROP TABLE IF EXISTS transactions')
    
    cursor.execute('''
        CREATE TABLE transactions (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT,
            amount_idr REAL,
            tx_date TEXT,
            tx_type TEXT,
            merchant_info TEXT
        )
    ''')
    
    start_date = datetime.now() - timedelta(days=30)
    
    for _ in range(900):
        acc = f"ACC_{random.randint(100, 500)}"
        amt = random.uniform(50_000, 5_000_000)
        date = start_date + timedelta(days=random.randint(0, 30))
        cursor.execute("INSERT INTO transactions (account_id, amount_idr, tx_date, tx_type, merchant_info) VALUES (?, ?, ?, ?, ?)",
                       (acc, amt, date.strftime("%Y-%m-%d %H:%M:%S"), "TRANSFER", "DOMESTIC_TRANSFER"))
        
    judol_mule_acc = "ACC_777_JUDOL_MULE"
    
    for i in range(50):
        amt = random.choice([25000, 50000, 100000]) 
        date = start_date + timedelta(minutes=i*10)
        cursor.execute("INSERT INTO transactions (account_id, amount_idr, tx_date, tx_type, merchant_info) VALUES (?, ?, ?, ?, ?)",
                       (judol_mule_acc, amt, date.strftime("%Y-%m-%d %H:%M:%S"), "DEPOSIT", "PEER_TO_PEER"))
        
    cursor.execute("INSERT INTO transactions (account_id, amount_idr, tx_date, tx_type, merchant_info) VALUES (?, ?, ?, ?, ?)",
                   (judol_mule_acc, 500000000, (start_date + timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S"), "WITHDRAWAL", "OFFSHORE_CRYPTO_EXCHANGE"))
        
    conn.commit()
    conn.close()
    print("✓ SQLite Database initialized with Judi Online (Judol) patterns.")


#3  VECTOR STORE SETUP

def setup_vector_database():
    pdf_filename = "UU_PDP_27_2022.pdf"
    
    if not os.path.exists(pdf_filename):
        print(f"\n ERROR: Could not find '{pdf_filename}'!")
        exit(1)

    print(f"Loading actual PDP Law document ({pdf_filename})...")
    embeddings = HuggingFaceEmbeddings(model_name="paraphrase-multilingual-MiniLM-L12-v2") 
    
    loader = PyPDFLoader(pdf_filename)
    documents = loader.load()
    
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200, length_function=len)
    chunks = text_splitter.split_documents(documents)
    
    vectorstore = Chroma.from_documents(chunks, embeddings, collection_name="pdp_law")
    print(f"✓ ChromaDB initialized with {len(chunks)} multilingual chunks.")
    return vectorstore


#4  STATE DEFINITION FOR ORCHESTRATOR

class ComplianceState(TypedDict):
    account_id: str
    aml_findings: str
    legal_assessment: str
    final_sar_json: str
    audit_trail: List[str]


#5  AGENTS DEFINITION

def financial_investigator_node(state: ComplianceState) -> ComplianceState:
    state["audit_trail"].append(f"[{datetime.now().isoformat()}] INITIATED: Financial Investigator Node.")
    print("\nAgent 2 (Financial Investigator) is hunting for Mule Accounts...")
    
    db = SQLDatabase.from_uri(f"sqlite:///{DB_FILE}")
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    
    tools = toolkit.get_tools()
    agent = create_react_agent(llm, tools)
    
    prompt = """
    You are a financial investigator hunting for Online Gambling (Judi Online) 'mule' accounts. 
    Table 'transactions' has columns: tx_id, account_id, amount_idr, tx_date, tx_type, merchant_info.
    Definition of a Mule Account: An account that receives more than 20 'DEPOSIT' transactions where the amount_idr is <= 100000.
    
    Example SQL:
    SELECT account_id, COUNT(*) as depo_count FROM transactions WHERE tx_type = 'DEPOSIT' AND amount_idr <= 100000 GROUP BY account_id HAVING depo_count > 20;
    
    Execute the query. Return ONLY the exact Account ID and describe the behavior as 'Suspected Judi Online Mule Account'.
    """
    
    try:
        result = agent.invoke({"messages": [("user", prompt)]})
        findings = result["messages"][-1].content 
        
        acc_id = "ACC_777_JUDOL_MULE" if "ACC_777_JUDOL_MULE" in findings else "UNKNOWN_ACCOUNT"
        state["account_id"] = acc_id
        state["aml_findings"] = findings
        state["audit_trail"].append(f"[{datetime.now().isoformat()}] COMPLETED: Financial Investigator identified {acc_id}.")
    except Exception as e:
        state["aml_findings"] = f"Investigation Failed: {str(e)}"
        
    return state

def legal_analyst_node(state: ComplianceState) -> ComplianceState:
    state["audit_trail"].append(f"[{datetime.now().isoformat()}] INITIATED: Legal Analyst Node for {state['account_id']}.")
    print("\nAgent 1 (Legal Analyst) is cross-referencing Indonesian PDP Law...")
    
    vectorstore = setup_vector_database()
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
    retriever_tool = create_retriever_tool(retriever, "search_pdp_law", "Searches UU PDP No 27 of 2022.")
    
    tools = [retriever_tool]
    agent = create_react_agent(llm, tools)
    
    legal_query = f"""
    You are a Legal Compliance AI. 
    We suspect {state['account_id']} is a Judi Online mule account using stolen KTP data. We want to share data with foreign law enforcement without consent.
    CRITICAL: The document is in Bahasa Indonesia. Use keywords: 'pengecualian persetujuan', 'penegakan hukum', 'pidana'.
    
    Answer in English:
    1. Does the PDP Law allow us to share personal data WITHOUT consent for law enforcement?
    2. What are the specific criminal penalties (hukuman pidana penjara / denda) for using false personal data?
    """
    
    result = agent.invoke({"messages": [("user", legal_query)]})
    state["legal_assessment"] = result["messages"][-1].content
    state["audit_trail"].append(f"[{datetime.now().isoformat()}] COMPLETED: Legal Analyst formulated assessment.")
    return state

def sar_generator_node(state: ComplianceState) -> ComplianceState:
    state["audit_trail"].append(f"[{datetime.now().isoformat()}] INITIATED: SAR Generation.")
    print("\nOrchestrator is compiling the final Suspicious Activity Report (SAR)...")
    
    system_prompt = f"""
    Output ONLY a STRICT, VALID JSON payload representing the Suspicious Activity Report. 
    
    CRITICAL JSON RULES:
    1. Do not include any conversational text, greetings, or markdown outside the JSON.
    2. All keys and string values MUST be enclosed in double quotes.
    3. If an article number contains parentheses or symbols (like 67(1) or 68), you MUST output it as a string wrapped in quotes (e.g., "67(1)"). Do not leave it as an unquoted number!
    
    Context:
    Account ID: {state['account_id']}
    AML Findings: {state['aml_findings']}
    Legal Assessment: {state['legal_assessment']}
    
    JSON Schema:
    {{
        "report_type": "Suspicious Activity Report",
        "scenario": "Online Gambling (Judi Online) Mule Account",
        "account_id": "...",
        "suspicious_activity_summary": "...",
        "legal_and_pdp_assessment": "..."
    }}
    """
    
    response = llm.invoke(system_prompt)
    raw_text = response.content.strip()
    

    # Find the first '{' and the last '}' to extract only the JSON
    start_idx = raw_text.find('{')
    end_idx = raw_text.rfind('}')
    
    if start_idx != -1 and end_idx != -1:
        json_text = raw_text[start_idx:end_idx+1] # Extract just the JSON block
    else:
        json_text = raw_text # Fallback
        
    state["final_sar_json"] = json_text
    state["audit_trail"].append(f"[{datetime.now().isoformat()}] COMPLETED: SAR JSON successfully generated.")
    return state


#6 PDF EXPORT MODULE

def generate_pdf_sar(parsed_json: dict, filename: str = "Final_SAR_Report.pdf"):
    """Converts the JSON output into a formal, human-readable PDF document."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Title Header
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "OFFICIAL SUSPICIOUS ACTIVITY REPORT (SAR)", ln=True, align="C")
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 10, f"Generated automatically by AI RegTech Orchestrator on {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align="C")
    pdf.ln(10)
    

    def write_section(data, indent=0):
        if isinstance(data, dict):
            for key, value in data.items():
                pdf.set_font("Helvetica", "B", max(10, 13 - indent))
                formatted_key = str(key).replace('_', ' ').title()
                pdf.cell(0, 8, f"{'   ' * indent}{formatted_key}:", ln=True)
                write_section(value, indent + 1)
        elif isinstance(data, list):
            for item in data:
                write_section(item, indent + 1)
                pdf.ln(2)
        else:
            pdf.set_font("Helvetica", "", 11)
            # Encode/Decode to handle potential special characters
            safe_text = str(data).encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(0, 6, f"{'   ' * indent}{safe_text}")
            pdf.ln(2)

    write_section(parsed_json)
    
    # Footer Sign-off
    pdf.ln(15)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "AUTHORIZATION:", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, "System: Local LLM Orchestrator (Llama 3.1 + LangGraph)", ln=True)
    pdf.cell(0, 8, "Status: PENDING CCO REVIEW", ln=True)
    
    pdf.output(filename)
    return filename


#7  LANGGRAPH ORCHESTRATION (THE WORKFLOW)

def build_and_run_workflow():
    print("\n" + "="*50)
    print("🚀 BUILDING REGTECH EXECUTION GRAPH 🚀")
    print("="*50)
    
    workflow = StateGraph(ComplianceState)
    
    workflow.add_node("Investigator", financial_investigator_node)
    workflow.add_node("LegalAnalyst", legal_analyst_node)
    workflow.add_node("SARGenerator", sar_generator_node)
    
    workflow.set_entry_point("Investigator")
    workflow.add_edge("Investigator", "LegalAnalyst")
    workflow.add_edge("LegalAnalyst", "SARGenerator")
    workflow.add_edge("SARGenerator", END)
    
    app = workflow.compile()
    
    initial_state = ComplianceState(account_id="", aml_findings="", legal_assessment="", final_sar_json="", audit_trail=[])
    final_state = app.invoke(initial_state)
    

    print("\n\n" + "="*70)
    print("REGTECH AUDIT TRAIL")
    print("="*70)
    for entry in final_state["audit_trail"]:
        print(entry)
        
    print("\n" + "="*70)
    print("HUMAN READABLE SAR SUMMARY")
    print("="*70)
    
    try:
        parsed_sar = json.loads(final_state["final_sar_json"])
        
        # Print nicely to the console hehehe
        for key, value in parsed_sar.items():
            print(f"\n🔹 {key.replace('_', ' ').upper()}:")
            print(f"   {value}")
            
        # Generate the formal PDF
        pdf_name = f"SAR_{parsed_sar.get('account_id', 'REPORT')}.pdf"
        generate_pdf_sar(parsed_sar, filename=pdf_name)
        
        print("\n" + "="*70)
        print(f"SUCCESS: Formal PDF Report saved to your folder as -> {pdf_name}")
        print("="*70)
        
    except Exception as e:
        print("Failed to parse JSON cleanly. Raw LLM output:")
        print(final_state["final_sar_json"])
        print(f"Error details: {e}")

if __name__ == "__main__":
    setup_sqlite_database()
    build_and_run_workflow()