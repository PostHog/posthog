"""Airtable source settings and constants"""

# Airtable API base URL
AIRTABLE_API_BASE_URL = "https://api.airtable.com/v0"
AIRTABLE_METADATA_API_BASE_URL = "https://api.airtable.com/v0/meta"

# Rate limit (5 requests per second per base)
REQUESTS_PER_SECOND = 5

# Pagination
PAGE_SIZE = 100  # Airtable's default and maximum page size
