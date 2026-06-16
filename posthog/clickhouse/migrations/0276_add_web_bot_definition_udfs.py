from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.bot_definition.sql import BOT_DEFINITION_UDFS_SQL

# Bot-detection UDFs (webAnalyticsIsBot / webAnalyticsBotName / …). SQL UDFs are macro-expanded
# at query-analysis time, so they need to exist wherever bot queries are analyzed — the same two
# routes the dict serves (see 0275): DATA (events-table queries) and AUX (web-analytics
# preaggregated tables). Bodies are multiMatch-based (Hyperscan), not dictGet — see
# posthog/models/bot_definition/sql.py for the rationale.
operations = [run_sql_with_exceptions(sql, node_roles=[NodeRole.DATA, NodeRole.AUX]) for sql in BOT_DEFINITION_UDFS_SQL]
