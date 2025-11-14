# QuickBooks API endpoints configuration
# Based on common endpoints from Airbyte, Fivetran, and Stitch Data

# List of QuickBooks API endpoints to sync
ENDPOINTS = [
    "Account",
    "Bill",
    "BillPayment",
    "Budget",
    "Class",
    "CreditMemo",
    "Customer",
    "Department",
    "Deposit",
    "Employee",
    "Estimate",
    "Invoice",
    "Item",
    "JournalEntry",
    "Payment",
    "Purchase",
    "PurchaseOrder",
    "RefundReceipt",
    "SalesReceipt",
    "TaxAgency",
    "TaxCode",
    "TaxRate",
    "Term",
    "TimeActivity",
    "Transfer",
    "VendorCredit",
    "Vendor",
]

# Incremental field configuration for each endpoint
# QuickBooks uses MetaData.LastUpdatedTime for tracking changes
INCREMENTAL_FIELDS = {
    endpoint: ["MetaData.LastUpdatedTime"] for endpoint in ENDPOINTS
}
