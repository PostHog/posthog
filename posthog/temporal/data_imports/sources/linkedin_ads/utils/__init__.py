"""LinkedIn Ads utilities and shared components."""

from .constants import (
    API_BASE_URL,
    API_MAX_RETRIES,
    API_RATE_LIMIT_DELAY,
    API_RETRY_DELAY,
    API_TIMEOUT,
    API_VERSION,
    DEFAULT_PAGE_SIZE,
    MAX_DATE_RANGE_DAYS,
    MAX_PAGES_SAFETY_LIMIT,
)
from .date_handler import LinkedinAdsDateHandler
from .schemas import ENDPOINTS, INCREMENTAL_FIELDS, LINKEDIN_ADS_ENDPOINTS, LINKEDIN_ADS_FIELDS, LinkedinAdsResource
from .types import (
    ConfigType,
    DateRange,
    FlattenedLinkedinDataType,
    IncrementalValue,
    LinkedinAccountType,
    LinkedinAnalyticsType,
    LinkedinApiMethod,
    LinkedinAuditStampsType,
    LinkedinCampaignGroupType,
    LinkedinCampaignType,
    LinkedinDateRangeType,
    LinkedinDateType,
    LinkedinVersionType,
    RequestParams,
    ResourceMethodTuple,
    ResponseData,
)
from .utils import (
    CIRCUIT_BREAKER_TIMEOUT,
    check_circuit_breaker,
    determine_primary_keys,
    flatten_data_item,
    record_failure,
    record_success,
    validate_account_id,
    validate_date_format,
    validate_pivot_value,
)

# Explicit exports for better IDE support
__all__ = [
    # Types
    "LinkedinAccountType",
    "LinkedinCampaignType",
    "LinkedinCampaignGroupType",
    "LinkedinAnalyticsType",
    "LinkedinDateType",
    "LinkedinDateRangeType",
    "LinkedinAuditStampsType",
    "LinkedinVersionType",
    "FlattenedLinkedinDataType",
    "ConfigType",
    "IncrementalValue",
    "RequestParams",
    "ResponseData",
    "DateRange",
    "LinkedinApiMethod",
    "ResourceMethodTuple",

    # Schemas
    "LinkedinAdsResource",
    "ENDPOINTS",
    "INCREMENTAL_FIELDS",
    "LINKEDIN_ADS_ENDPOINTS",
    "LINKEDIN_ADS_FIELDS",

    # Constants
    "API_BASE_URL",
    "API_VERSION",
    "API_MAX_RETRIES",
    "API_RATE_LIMIT_DELAY",
    "API_RETRY_DELAY",
    "API_TIMEOUT",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGES_SAFETY_LIMIT",
    "MAX_DATE_RANGE_DAYS",

    # Utils
    "LinkedinAdsDateHandler",
    "CIRCUIT_BREAKER_TIMEOUT",
    "validate_account_id",
    "validate_date_format",
    "validate_pivot_value",
    "flatten_data_item",
    "determine_primary_keys",
    "check_circuit_breaker",
    "record_success",
    "record_failure",
]
