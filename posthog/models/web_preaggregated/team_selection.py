from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import ReplacingMergeTree
from posthog.settings.data_stores import CLICKHOUSE_DATABASE, CLICKHOUSE_PASSWORD, CLICKHOUSE_USER

WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_NAME = "web_pre_aggregated_teams"
WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME = "web_pre_aggregated_teams_dict"

# Default team IDs (fallback)
DEFAULT_ENABLED_TEAM_IDS = [1, 2, 55348, 47074, 12669, 1589, 117126]

# Strategy configurations
DEFAULT_TOP_TEAMS_BY_PAGEVIEWS_LIMIT = 30
# We want to limit the number of teams we proactively add while in beta
MAX_TOP_TEAMS_BY_PAGEVIEWS_LIMIT = 100


def get_top_teams_by_median_pageviews_sql(limit: int = DEFAULT_TOP_TEAMS_BY_PAGEVIEWS_LIMIT) -> str:
    if not isinstance(limit, int) or limit < 1 or limit > MAX_TOP_TEAMS_BY_PAGEVIEWS_LIMIT:
        raise ValueError(
            f"Invalid limit: {limit}. Must be an integer between 1 and {MAX_TOP_TEAMS_BY_PAGEVIEWS_LIMIT}."
        )

    return f"""
SELECT
    team_id,
    median(daily_pageviews) AS median_daily_pageviews
FROM (
    SELECT
        team_id,
        toDate(timestamp) AS day,
        count() AS daily_pageviews
    FROM events
    WHERE timestamp >= now() - INTERVAL 30 DAY
      AND event = '$pageview'
    GROUP BY
        team_id,
        day
)
GROUP BY team_id
ORDER BY median_daily_pageviews DESC
LIMIT {limit}
"""


def WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_SQL(on_cluster=True):
    return """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause} (
    team_id UInt64,
    enabled_by String DEFAULT 'system',
    version UInt32 DEFAULT toUnixTimestamp(now())
) ENGINE = {engine}
ORDER BY (team_id);
""".format(
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        table_name=f"`{WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_NAME}`",
        engine=ReplacingMergeTree("web_analytics_team_selection", ver="version"),
    )


def WEB_PRE_AGGREGATED_TEAM_SELECTION_DATA_SQL(team_ids: list[int] | None = None):
    if team_ids is None:
        team_ids = DEFAULT_ENABLED_TEAM_IDS

    values = ",\n".join(f"({team_id}, 'system')" for team_id in team_ids)

    return f"""
INSERT INTO `{WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_NAME}` (team_id, enabled_by) VALUES
  {values};"""


def WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_QUERY():
    return f"""
SELECT
    team_id
FROM
    `{CLICKHOUSE_DATABASE}`.`{WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_NAME}`
FINAL
WHERE version > 0
""".replace("\n", " ").strip()


def WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL(on_cluster=True):
    return """
CREATE DICTIONARY IF NOT EXISTS {dictionary_name} {on_cluster_clause} (
    team_id UInt64
)
PRIMARY KEY team_id
SOURCE(CLICKHOUSE(QUERY '{query}' USER '{clickhouse_user}' PASSWORD '{clickhouse_password}'))
LIFETIME(MIN 3000 MAX 3600)
LAYOUT(HASHED())""".format(
        dictionary_name=f"`{WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME}`",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        query=WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_QUERY(),
        clickhouse_user=CLICKHOUSE_USER,
        clickhouse_password=CLICKHOUSE_PASSWORD,
    )


def DROP_WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_SQL(on_cluster=True):
    return f"""
DROP TABLE IF EXISTS `{WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_NAME}` {ON_CLUSTER_CLAUSE(on_cluster)}
""".strip()


def DROP_WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL(on_cluster=True):
    return f"""
DROP DICTIONARY IF EXISTS `{WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME}` {ON_CLUSTER_CLAUSE(on_cluster)}
""".strip()
