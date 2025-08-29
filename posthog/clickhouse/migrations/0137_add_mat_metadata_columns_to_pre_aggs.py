from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.web_preaggregated.migrations import add_mat_metadata_fields_to_table

# Add mat_metadata_loggedIn and mat_metadata_backend columns to existing web analytics tables in all clusters
# The columns will exist everywhere but only be populated with data in EU cluster
operations = [
    run_sql_with_exceptions(
        add_mat_metadata_fields_to_table("web_pre_aggregated_stats"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        add_mat_metadata_fields_to_table("web_pre_aggregated_bounces"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        add_mat_metadata_fields_to_table("web_pre_aggregated_stats_staging"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        add_mat_metadata_fields_to_table("web_pre_aggregated_bounces_staging"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
    # Below are the v1 tables, let's keep the same schema on them to keep things compatible
    run_sql_with_exceptions(
        add_mat_metadata_fields_to_table("web_stats_hourly"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        add_mat_metadata_fields_to_table("web_bounces_hourly"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        add_mat_metadata_fields_to_table("web_stats_daily"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        add_mat_metadata_fields_to_table("web_bounces_daily"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        add_mat_metadata_fields_to_table("web_stats_hourly_staging"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        add_mat_metadata_fields_to_table("web_bounces_hourly_staging"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
]
