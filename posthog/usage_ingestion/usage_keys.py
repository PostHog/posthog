# Warehouse sources bill rows on this key, and batch exports do too from the unified pricing cutover.
# It lives outside both products so that neither has to import the other to share it.
ROWS_SYNCED_USAGE_KEY = "warehouse_rows_synced"
