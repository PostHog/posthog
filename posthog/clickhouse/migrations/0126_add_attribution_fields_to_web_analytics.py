from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_COMBINED_VIEW_SQL,
    WEB_BOUNCES_COMBINED_VIEW_SQL,
)

# Attribution fields to add (in order)
ATTRIBUTION_FIELDS = ["has_gclid", "has_gad_source_paid_search", "has_fbclid"]

# Web analytics tables to update
WEB_ANALYTICS_TABLES = [
    "web_stats_daily",
    "web_bounces_daily",
    "web_stats_hourly",
    "web_bounces_hourly",
    "web_stats_hourly_staging",
    "web_bounces_hourly_staging",
]


def create_attribution_field_operations():
    operations = []

    for table_name in WEB_ANALYTICS_TABLES:
        # Add each attribution field in sequence
        prev_column = "region_name"
        for field_name in ATTRIBUTION_FIELDS:
            operations.append(
                run_sql_with_exceptions(
                    f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {field_name} Bool AFTER {prev_column}",
                    node_role=NodeRole.ALL,
                )
            )
            prev_column = field_name

    return operations


def create_view_recreation_operations():
    return [
        # Drop existing views
        run_sql_with_exceptions("DROP VIEW IF EXISTS web_stats_combined SYNC", node_role=NodeRole.ALL),
        run_sql_with_exceptions("DROP VIEW IF EXISTS web_bounces_combined SYNC", node_role=NodeRole.ALL),
        # Recreate views with new schema
        run_sql_with_exceptions(WEB_STATS_COMBINED_VIEW_SQL(), node_role=NodeRole.ALL),
        run_sql_with_exceptions(WEB_BOUNCES_COMBINED_VIEW_SQL(), node_role=NodeRole.ALL),
    ]


operations = create_attribution_field_operations() + create_view_recreation_operations()
