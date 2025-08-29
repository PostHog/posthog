"""LinkedIn Ads data source for PostHog.

This package provides a clean, production-ready integration with LinkedIn Marketing API
organized into focused modules:

- client/: API client components and HTTP handling
- service/: Business logic and data coordination
- utils/: Shared utilities, types, and schemas

Main entry points:
- linkedin_ads_source(): Main data fetching function
- LinkedinAdsSource: PostHog source integration class
"""

from .client import LinkedinAdsAuthError, LinkedinAdsClient, LinkedinAdsError, LinkedinAdsRateLimitError
from .linkedin_ads import get_incremental_fields, get_schemas, linkedin_ads_source
from .source import LinkedinAdsSource

__all__ = [
    # Main functions
    "get_incremental_fields",
    "get_schemas",
    "linkedin_ads_source",

    # PostHog integration
    "LinkedinAdsSource",

    # Client components
    "LinkedinAdsClient",
    "LinkedinAdsError",
    "LinkedinAdsAuthError",
    "LinkedinAdsRateLimitError",
]
