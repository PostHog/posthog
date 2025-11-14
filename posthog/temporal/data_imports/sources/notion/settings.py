# Notion API endpoints that can be synced
ENDPOINTS = [
    "blocks",
    "comments",
    "databases",
    "pages",
    "users",
]

# Endpoints that support incremental syncing
INCREMENTAL_ENDPOINTS = {
    "blocks": "last_edited_time",
    "comments": "created_time",
    "databases": "last_edited_time",
    "pages": "last_edited_time",
}
