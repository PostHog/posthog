"""
Salesforce enrichment workflow components.

This module provides PostHog's Salesforce account enrichment functionality using
Harmonic company data. It includes async workflows optimized for concurrent API
processing and bulk Salesforce updates.

Main Components:
- enrich_accounts_chunked_async: Core enrichment workflow function
- AsyncHarmonicClient: Concurrent Harmonic API client
- SalesforceClient: Salesforce API client for bulk updates
- Constants: Performance-tuned batch sizes and limits

Usage:
    from ee.billing.salesforce_enrichment import (
        enrich_accounts_chunked_async,
        AsyncHarmonicClient,
        HARMONIC_BATCH_SIZE
    )
"""

# Main enrichment function
from .enrichment import enrich_accounts_chunked_async

# API clients
from .harmonic_client import AsyncHarmonicClient
from .salesforce_client import SalesforceClient

# Configuration constants
from .constants import (
    HARMONIC_BATCH_SIZE,
    SALESFORCE_UPDATE_BATCH_SIZE,
    HARMONIC_DEFAULT_MAX_CONCURRENT_REQUESTS,
    HARMONIC_REQUEST_TIMEOUT_SECONDS,
    REDIS_TTL_SECONDS,
    SALESFORCE_ACCOUNTS_CACHE_KEY,
)

# Utility functions (commonly used by workflows and debug scripts)
from .enrichment import (
    transform_harmonic_data,
    prepare_salesforce_update_data,
    is_excluded_domain,
)

# Redis cache utilities (for workflow implementations)
from .redis_cache import (
    store_accounts_in_redis,
    get_accounts_from_redis,
)

__all__ = [
    # Main workflow function
    "enrich_accounts_chunked_async",
    # API clients
    "AsyncHarmonicClient",
    "SalesforceClient",
    # Configuration constants
    "HARMONIC_BATCH_SIZE",
    "SALESFORCE_UPDATE_BATCH_SIZE",
    "HARMONIC_DEFAULT_MAX_CONCURRENT_REQUESTS",
    "HARMONIC_REQUEST_TIMEOUT_SECONDS",
    "REDIS_TTL_SECONDS",
    "SALESFORCE_ACCOUNTS_CACHE_KEY",
    # Data transformation utilities
    "transform_harmonic_data",
    "prepare_salesforce_update_data",
    "is_excluded_domain",
    # Redis cache utilities
    "store_accounts_in_redis",
    "get_accounts_from_redis",
]
