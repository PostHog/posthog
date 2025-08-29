"""LinkedIn Ads API constants and configuration."""

# LinkedIn URN constants
LINKEDIN_SPONSORED_URN_PREFIX = "urn:li:sponsored"

# API Configuration
API_BASE_URL = "https://api.linkedin.com/rest"
API_VERSION = "202508"  # August 2025 - current version
API_TIMEOUT = 30
API_MAX_RETRIES = 3
API_RETRY_DELAY = 5  # Base delay in seconds
API_RATE_LIMIT_DELAY = 60  # Rate limit retry delay

# Circuit breaker configuration
CIRCUIT_BREAKER_THRESHOLD = 5  # Max failures before circuit opens
CIRCUIT_BREAKER_TIMEOUT = 300  # 5 minutes in seconds

# Pagination configuration
DEFAULT_PAGE_SIZE = 100
MAX_PAGES_SAFETY_LIMIT = 1000

# Validation constraints
ACCOUNT_ID_MIN_LENGTH = 6
ACCOUNT_ID_MAX_LENGTH = 15

# Date range limits
MAX_DATE_RANGE_DAYS = 365 * 5  # 5 years

# Valid pivot values for analytics
VALID_PIVOT_VALUES = ["CAMPAIGN", "CAMPAIGN_GROUP", "CREATIVE", "ACCOUNT"]
