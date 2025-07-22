from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.web_preaggregated.team_config import (
    WEB_ANALYTICS_TEAM_CONFIG_TABLE_SQL,
    WEB_ANALYTICS_TEAM_CONFIG_DICTIONARY_SQL,
    WEB_ANALYTICS_TEAM_CONFIG_DATA_SQL,
    DEFAULT_ENABLED_TEAM_IDS,
)

operations = [
    run_sql_with_exceptions(WEB_ANALYTICS_TEAM_CONFIG_TABLE_SQL(), node_role=NodeRole.ALL),
    run_sql_with_exceptions(WEB_ANALYTICS_TEAM_CONFIG_DATA_SQL(DEFAULT_ENABLED_TEAM_IDS), node_role=NodeRole.ALL),
    run_sql_with_exceptions(WEB_ANALYTICS_TEAM_CONFIG_DICTIONARY_SQL(), node_role=NodeRole.ALL),
]
