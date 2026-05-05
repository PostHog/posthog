from typing import TypedDict

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


class SearchAnalyticsSchema(TypedDict):
    dimensions: list[str]
    primary_key: list[str]
    should_sync_default: bool
    description: str | None


# Each schema maps to a single Search Analytics query with a fixed dimension set.
# Primary key is always (date + dimensions) to allow merge-mode dedupe across re-syncs.
#
# Sampling note: Google's Search Analytics API caps results at ~50,000 rows per
# (property, date, dimension-set). When the cap is hit, rows are sorted by clicks
# descending and the tail is silently dropped. Schemas with more dimensions hit
# the cap faster (see `search_analytics_by_query_page` below). For full-fidelity
# data on high-traffic properties, the official BigQuery bulk export is the only
# escape hatch; see `google_search_console.py` for the full breakdown.
SEARCH_ANALYTICS_SCHEMAS: dict[str, SearchAnalyticsSchema] = {
    "search_analytics_by_date": {
        "dimensions": ["date"],
        "primary_key": ["date"],
        "should_sync_default": False,
        "description": "Daily totals for clicks, impressions, CTR, and average position.",
    },
    "search_analytics_by_query": {
        "dimensions": ["date", "query"],
        "primary_key": ["date", "query"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by search query (keyword). "
            "Sites with >50K distinct queries/day will lose long-tail keywords to API sampling."
        ),
    },
    "search_analytics_by_page": {
        "dimensions": ["date", "page"],
        "primary_key": ["date", "page"],
        "should_sync_default": False,
        "description": (
            "Daily performance broken out by landing page URL. "
            "Sites with >50K distinct landing pages/day will lose long-tail URLs to API sampling."
        ),
    },
    "search_analytics_by_country": {
        "dimensions": ["date", "country"],
        "primary_key": ["date", "country"],
        "should_sync_default": False,
        "description": "Daily performance broken out by country (ISO 3166-1 alpha-3).",
    },
    "search_analytics_by_device": {
        "dimensions": ["date", "device"],
        "primary_key": ["date", "device"],
        "should_sync_default": False,
        "description": "Daily performance broken out by device (DESKTOP, MOBILE, TABLET).",
    },
    "search_analytics_by_query_page": {
        "dimensions": ["date", "query", "page"],
        "primary_key": ["date", "query", "page"],
        "should_sync_default": True,
        "description": (
            "Daily performance broken out by both query and landing page. Most detailed table, "
            "but the cartesian over (query x page) hits Google's ~50K row/day API sampling cap "
            "fastest. Above the cap, only the top rows by clicks are returned and the tail is "
            "silently dropped. For full fidelity on high-traffic properties, use the per-query "
            "and per-page tables together, or rely on Google's BigQuery bulk export."
        ),
    },
}


SEARCH_ANALYTICS_INCREMENTAL_FIELD: IncrementalField = {
    "label": "date",
    "field": "date",
    "type": IncrementalFieldType.Date,
    "field_type": IncrementalFieldType.Date,
}
