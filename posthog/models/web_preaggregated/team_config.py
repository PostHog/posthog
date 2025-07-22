from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import ReplacingMergeTree
from posthog.settings.data_stores import CLICKHOUSE_DATABASE

# Table and dictionary names
WEB_ANALYTICS_TEAM_CONFIG_TABLE_NAME = "web_analytics_team_config"
WEB_ANALYTICS_TEAM_CONFIG_DICTIONARY_NAME = "web_analytics_team_config_dict"

# Default team IDs (fallback)
DEFAULT_ENABLED_TEAM_IDS = [1, 2, 55348, 47074, 12669, 1589, 117126]


def WEB_ANALYTICS_TEAM_CONFIG_TABLE_SQL(on_cluster=True):
    return """
CREATE TABLE IF NOT EXISTS {table_name} (
    team_id UInt64,
    enabled_at DateTime,
    enabled_by String DEFAULT 'system',
    version UInt32 DEFAULT toUnixTimestamp(now())
) ENGINE = {engine}
ORDER BY (team_id);
""".format(
        table_name=f"`{CLICKHOUSE_DATABASE}`.`{WEB_ANALYTICS_TEAM_CONFIG_TABLE_NAME}`",
        engine=ReplacingMergeTree("web_analytics_team_config", ver="version"),
    )


def DROP_WEB_ANALYTICS_TEAM_CONFIG_TABLE_SQL(on_cluster=True):
    return "DROP TABLE IF EXISTS {table_name} {on_cluster_clause}".format(
        table_name=f"`{CLICKHOUSE_DATABASE}`.`{WEB_ANALYTICS_TEAM_CONFIG_TABLE_NAME}`",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def TRUNCATE_WEB_ANALYTICS_TEAM_CONFIG_TABLE_SQL(on_cluster=True):
    return "TRUNCATE TABLE IF EXISTS {table_name} {on_cluster_clause}".format(
        table_name=f"`{CLICKHOUSE_DATABASE}`.`{WEB_ANALYTICS_TEAM_CONFIG_TABLE_NAME}`",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def WEB_ANALYTICS_TEAM_CONFIG_DATA_SQL(team_ids: list[int] | None = None):
    if team_ids is None:
        team_ids = DEFAULT_ENABLED_TEAM_IDS

    values = ",\n".join(f"({team_id}, now(), 'system')" for team_id in team_ids)

    return f"""
INSERT INTO `{CLICKHOUSE_DATABASE}`.`{WEB_ANALYTICS_TEAM_CONFIG_TABLE_NAME}` (team_id, enabled_at, enabled_by) VALUES
  {values};"""


def WEB_ANALYTICS_TEAM_CONFIG_DICTIONARY_QUERY():
    return f"""
SELECT
    team_id,
    argMax(enabled_at, version) AS enabled_at
FROM
    `{CLICKHOUSE_DATABASE}`.`{WEB_ANALYTICS_TEAM_CONFIG_TABLE_NAME}`
GROUP BY
    team_id
""".replace("\n", " ").strip()


def WEB_ANALYTICS_TEAM_CONFIG_DICTIONARY_SQL(on_cluster=True):
    return """
CREATE DICTIONARY IF NOT EXISTS {dictionary_name} {on_cluster_clause} (
    team_id UInt64,
    enabled_at DateTime
)
PRIMARY KEY team_id
SOURCE(CLICKHOUSE(QUERY '{query}'))
LIFETIME(MIN 3000 MAX 3600)
LAYOUT(HASHED())""".format(
        dictionary_name=f"`{CLICKHOUSE_DATABASE}`.`{WEB_ANALYTICS_TEAM_CONFIG_DICTIONARY_NAME}`",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        query=WEB_ANALYTICS_TEAM_CONFIG_DICTIONARY_QUERY(),
    )


def DROP_WEB_ANALYTICS_TEAM_CONFIG_DICTIONARY_SQL(on_cluster=True):
    return "DROP DICTIONARY IF EXISTS {dictionary_name} {on_cluster_clause}".format(
        dictionary_name=f"`{CLICKHOUSE_DATABASE}`.`{WEB_ANALYTICS_TEAM_CONFIG_DICTIONARY_NAME}`",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    ).strip()


def format_team_ids_for_sql(team_ids: list[int] | None = None) -> str:
    if not team_ids:
        return "1=1"
    return f"team_id IN({', '.join(str(team_id) for team_id in team_ids)})"
