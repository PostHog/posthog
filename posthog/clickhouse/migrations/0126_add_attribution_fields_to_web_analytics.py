from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_COMBINED_VIEW_SQL,
    WEB_BOUNCES_COMBINED_VIEW_SQL,
)
from posthog.models.web_preaggregated.migrations import (
    add_attribution_fields_to_table,
)

operations = [
    run_sql_with_exceptions(
        add_attribution_fields_to_table("web_stats_daily"), node_role=NodeRole.ALL, is_alter_on_replicated_table=True
    ),
    run_sql_with_exceptions(
        add_attribution_fields_to_table("web_bounces_daily"), node_role=NodeRole.ALL, is_alter_on_replicated_table=True
    ),
    run_sql_with_exceptions(
        add_attribution_fields_to_table("web_stats_hourly"), node_role=NodeRole.ALL, is_alter_on_replicated_table=True
    ),
    run_sql_with_exceptions(
        add_attribution_fields_to_table("web_bounces_hourly"), node_role=NodeRole.ALL, is_alter_on_replicated_table=True
    ),
    run_sql_with_exceptions(
        add_attribution_fields_to_table("web_stats_hourly_staging"),
        node_role=NodeRole.ALL,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        add_attribution_fields_to_table("web_bounces_hourly_staging"),
        node_role=NodeRole.ALL,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(WEB_STATS_COMBINED_VIEW_SQL(), node_role=NodeRole.ALL),
    run_sql_with_exceptions(WEB_BOUNCES_COMBINED_VIEW_SQL(), node_role=NodeRole.ALL),
]
