from django.conf import settings

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

# V1 Sessions table
TABLE_BASE_NAME = "sessions"


def SESSIONS_DATA_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def TRUNCATE_SESSIONS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SESSIONS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


def DROP_SESSION_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SESSIONS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


def DROP_SESSION_MATERIALIZED_VIEW_SQL():
    return f"DROP TABLE IF EXISTS {TABLE_BASE_NAME}_mv {ON_CLUSTER_CLAUSE()}"


def DROP_SESSION_VIEW_SQL():
    return f"DROP VIEW IF EXISTS {TABLE_BASE_NAME}_v {ON_CLUSTER_CLAUSE()}"


# Only teams that were grandfathered into the V1 sessions table are allowed to use it. Everyone else should use V2,
# i.e. raw_sessions. These teams were those who were seen to have changed their session table version in these metabase
# queries:
# US: https://metabase.prod-us.posthog.dev/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7InR5cGUiOiJuYXRpdmUiLCJuYXRpdmUiOnsicXVlcnkiOiJTRUxFQ1QgdGVhbV9pZCwgc1xuRlJPTSAoXG4gICAgU0VMRUNUIG1vZGlmaWVycy0-PidzZXNzaW9uVGFibGVWZXJzaW9uJyBBUyBzLCBpZCBhcyB0ZWFtX2lkXG4gICAgRlJPTSBwb3N0aG9nX3RlYW1cbikgc3ViXG5XSEVSRSBzICE9ICcnIiwidGVtcGxhdGUtdGFncyI6e319LCJkYXRhYmFzZSI6MzR9LCJkaXNwbGF5IjoidGFibGUiLCJwYXJhbWV0ZXJzIjpbXSwidmlzdWFsaXphdGlvbl9zZXR0aW5ncyI6e319
# EU: https://metabase.prod-eu.posthog.dev/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7InR5cGUiOiJuYXRpdmUiLCJuYXRpdmUiOnsicXVlcnkiOiJTRUxFQ1QgdGVhbV9pZCwgc1xuRlJPTSAoXG4gICAgU0VMRUNUIG1vZGlmaWVycy0-PidzZXNzaW9uVGFibGVWZXJzaW9uJyBBUyBzLCBpZCBhcyB0ZWFtX2lkXG4gICAgRlJPTSBwb3N0aG9nX3RlYW1cbikgc3ViXG5XSEVSRSBzICE9ICcnIiwidGVtcGxhdGUtdGFncyI6e319LCJkYXRhYmFzZSI6MzR9LCJkaXNwbGF5IjoidGFibGUiLCJwYXJhbWV0ZXJzIjpbXSwidmlzdWFsaXphdGlvbl9zZXR0aW5ncyI6e319
# or had contacted support about an issue.
# This list exists because we want to reduce the number of writes happening to this table, and so we don't write to it
# for any team not in this list. Adding a team to this is possible if needed, but would require changing this MV in
# production and backfilling this table with the management command backfill_sessions_table.
ALLOWED_TEAM_IDS = [
    # posthog
    1,
    2,
    # US query
    13610,  # zendesk: https://posthoghelp.zendesk.com/agent/tickets/18001
    19279,
    21173,
    29929,
    32050,
    # EU query
    9910,
    11775,
    21129,
    31490,
]
ALLOWED_TEAM_IDS_SQL = ", ".join(str(team_id) for team_id in ALLOWED_TEAM_IDS)

# if updating these column definitions
# you'll need to update the explicit column definitions in the materialized view creation statement below
SESSIONS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    -- ClickHouse will pick any value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id SimpleAggregateFunction(any, String),

    min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),

    urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    entry_url AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    exit_url AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
    initial_referring_domain AggregateFunction(argMin, String, DateTime64(6, 'UTC')),

    initial_utm_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_campaign AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_medium AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_term AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_content AggregateFunction(argMin, String, DateTime64(6, 'UTC')),

    -- Other Ad / campaign / attribution IDs
    initial_gclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gad_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gclsrc AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_dclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_wbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_fbclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_msclkid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_twclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_li_fat_id AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_mc_cid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_igshid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_ttclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_epik AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_qclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_sccid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),

    -- create a map of how many times we saw each event
    event_count_map SimpleAggregateFunction(sumMap, Map(String, Int64)),
    -- duplicate the event count as a specific column for pageviews and autocaptures,
    -- as these are used in some key queries and need to be fast
    pageview_count SimpleAggregateFunction(sum, Int64),
    autocapture_count SimpleAggregateFunction(sum, Int64),
) ENGINE = {engine}
"""


def SESSIONS_DATA_TABLE_ENGINE():
    return AggregatingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED)


def SESSIONS_TABLE_SQL(on_cluster=True):
    return (
        SESSIONS_TABLE_BASE_SQL
        + """
    PARTITION BY toYYYYMM(min_timestamp)
    -- order by is used by the aggregating merge tree engine to
    -- identify candidates to merge, e.g. toDate(min_timestamp)
    -- would mean we would have one row per day per session_id
    -- if CH could completely merge to match the order by
    -- it is also used to organise data to make queries faster
    -- we want the fewest rows possible but also the fastest queries
    -- since we query by date and not by time
    -- and order by must be in order of increasing cardinality
    -- so we order by date first, then team_id, then session_id
    -- hopefully, this is a good balance between the two
    ORDER BY (toStartOfDay(min_timestamp), team_id, session_id)
SETTINGS index_granularity=512
"""
    ).format(
        table_name=SESSIONS_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=SESSIONS_DATA_TABLE_ENGINE(),
    )


def source_column(column_name: str) -> str:
    return trim_quotes_expr(f"JSONExtractRaw(properties, '{column_name}')")


SESSION_TABLE_MV_SELECT_SQL = (
    lambda: """
SELECT

`$session_id` as session_id,
team_id,

-- it doesn't matter which distinct_id gets picked (it'll be somewhat random) as they can all join to the right person
any(distinct_id) as distinct_id,

min(timestamp) AS min_timestamp,
max(timestamp) AS max_timestamp,

groupUniqArray({current_url_property}) AS urls,
argMinState({current_url_property}, timestamp) as entry_url,
argMaxState({current_url_property}, timestamp) as exit_url,

argMinState({referring_domain_property}, timestamp) as initial_referring_domain,
argMinState({utm_source_property}, timestamp) as initial_utm_source,
argMinState({utm_campaign_property}, timestamp) as initial_utm_campaign,
argMinState({utm_medium_property}, timestamp) as initial_utm_medium,
argMinState({utm_term_property}, timestamp) as initial_utm_term,
argMinState({utm_content_property}, timestamp) as initial_utm_content,
argMinState({gclid_property}, timestamp) as initial_gclid,
argMinState({gad_source_property}, timestamp) as initial_gad_source,
argMinState({gclsrc_property}, timestamp) as initial_gclsrc,
argMinState({dclid_property}, timestamp) as initial_dclid,
argMinState({gbraid_property}, timestamp) as initial_gbraid,
argMinState({wbraid_property}, timestamp) as initial_wbraid,
argMinState({fbclid_property}, timestamp) as initial_fbclid,
argMinState({msclkid_property}, timestamp) as initial_msclkid,
argMinState({twclid_property}, timestamp) as initial_twclid,
argMinState({li_fat_id_property}, timestamp) as initial_li_fat_id,
argMinState({mc_cid_property}, timestamp) as initial_mc_cid,
argMinState({igshid_property}, timestamp) as initial_igshid,
argMinState({ttclid_property}, timestamp) as initial_ttclid,
argMinState({epik_property}, timestamp) as initial_epik,
argMinState({qclid_property}, timestamp) as initial_qclid,
argMinState({sccid_property}, timestamp) as initial_sccid,

sumMap(CAST(([event], [1]), 'Map(String, UInt64)')) as event_count_map,
sumIf(1, event='$pageview') as pageview_count,
sumIf(1, event='$autocapture') as autocapture_count

FROM {database}.sharded_events
WHERE `$session_id` IS NOT NULL AND `$session_id` != '' AND team_id IN ({allowed_team_ids})
GROUP BY `$session_id`, team_id
""".format(
        database=settings.CLICKHOUSE_DATABASE,
        current_url_property=source_column("$current_url"),
        referring_domain_property=source_column("$referring_domain"),
        utm_source_property=source_column("utm_source"),
        utm_campaign_property=source_column("utm_campaign"),
        utm_medium_property=source_column("utm_medium"),
        utm_term_property=source_column("utm_term"),
        utm_content_property=source_column("utm_content"),
        gclid_property=source_column("gclid"),
        gad_source_property=source_column("gad_source"),
        gclsrc_property=source_column("gclsrc"),
        dclid_property=source_column("dclid"),
        gbraid_property=source_column("gbraid"),
        wbraid_property=source_column("wbraid"),
        fbclid_property=source_column("fbclid"),
        msclkid_property=source_column("msclkid"),
        twclid_property=source_column("twclid"),
        li_fat_id_property=source_column("li_fat_id"),
        mc_cid_property=source_column("mc_cid"),
        igshid_property=source_column("igshid"),
        ttclid_property=source_column("ttclid"),
        epik_property=source_column("epik"),
        qclid_property=source_column("qclid"),
        sccid_property=source_column("sccid"),
        allowed_team_ids=ALLOWED_TEAM_IDS_SQL,
    )
)

SESSIONS_TABLE_MV_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name} {on_cluster_clause}
TO {database}.{target_table}
AS
{select_sql}
""".format(
        table_name=f"{TABLE_BASE_NAME}_mv",
        target_table=f"writable_{TABLE_BASE_NAME}",
        on_cluster_clause=ON_CLUSTER_CLAUSE(),
        database=settings.CLICKHOUSE_DATABASE,
        select_sql=SESSION_TABLE_MV_SELECT_SQL(),
    )
)

SESSION_TABLE_UPDATE_SQL = (
    lambda: """
ALTER TABLE {table_name} MODIFY QUERY
{select_sql}
""".format(
        table_name=f"{TABLE_BASE_NAME}_mv",
        select_sql=SESSION_TABLE_MV_SELECT_SQL(),
    )
)

# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_sessions based on a sharding key.


def WRITABLE_SESSIONS_TABLE_SQL(on_cluster=True):
    return SESSIONS_TABLE_BASE_SQL.format(
        table_name=f"writable_{TABLE_BASE_NAME}",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SESSIONS_DATA_TABLE(),
            # shard via session_id so that all events for a session are on the same shard
            sharding_key="sipHash64(session_id)",
        ),
    )


# This table is responsible for reading from sessions on a cluster setting


def DISTRIBUTED_SESSIONS_TABLE_SQL(on_cluster=True):
    return SESSIONS_TABLE_BASE_SQL.format(
        table_name=TABLE_BASE_NAME,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SESSIONS_DATA_TABLE(),
            sharding_key="sipHash64(session_id)",
        ),
    )


# This is the view that can be queried directly, that handles aggregation of potentially multiple rows per session.
# Most queries won't use this directly as they will want to pre-filter rows before aggregation, but it's useful for
# debugging
SESSIONS_VIEW_SQL = (
    lambda: f"""
CREATE OR REPLACE VIEW {TABLE_BASE_NAME}_v {ON_CLUSTER_CLAUSE()} AS
SELECT
    session_id,
    team_id,
    any(distinct_id) as distinct_id,
    min(min_timestamp) as min_timestamp,
    max(max_timestamp) as max_timestamp,
    arrayDistinct(arrayFlatten(groupArray(urls)) )AS urls,
    argMinMerge(entry_url) as entry_url,
    argMaxMerge(exit_url) as exit_url,
    argMinMerge(initial_utm_source) as initial_utm_source,
    argMinMerge(initial_utm_campaign) as initial_utm_campaign,
    argMinMerge(initial_utm_medium) as initial_utm_medium,
    argMinMerge(initial_utm_term) as initial_utm_term,
    argMinMerge(initial_utm_content) as initial_utm_content,
    argMinMerge(initial_referring_domain) as initial_referring_domain,
    argMinMerge(initial_gclid) as initial_gclid,
    argMinMerge(initial_gad_source) as initial_gad_source,
    argMinMerge(initial_gclsrc) as initial_gclsrc,
    argMinMerge(initial_dclid) as initial_dclid,
    argMinMerge(initial_gbraid) as initial_gbraid,
    argMinMerge(initial_wbraid) as initial_wbraid,
    argMinMerge(initial_fbclid) as initial_fbclid,
    argMinMerge(initial_msclkid) as initial_msclkid,
    argMinMerge(initial_twclid) as initial_twclid,
    argMinMerge(initial_li_fat_id) as initial_li_fat_id,
    argMinMerge(initial_mc_cid) as initial_mc_cid,
    argMinMerge(initial_igshid) as initial_igshid,
    argMinMerge(initial_ttclid) as initial_ttclid,
    argMinMerge(initial_epik) as initial_epik,
    argMinMerge(initial_qclid) as initial_qclid,
    argMinMerge(initial_sccid) as initial_sccid,
    sumMap(event_count_map) as event_count_map,
    sum(pageview_count) as pageview_count,
    sum(autocapture_count) as autocapture_count
FROM sessions
GROUP BY session_id, team_id
"""
)

SELECT_SESSION_PROP_STRING_VALUES_SQL = """
SELECT
    value,
    count(value)
FROM (
    SELECT
        {property_expr} as value
    FROM
        sessions
    WHERE
        team_id = %(team_id)s AND
        {property_expr} IS NOT NULL AND
        {property_expr} != ''
    ORDER BY session_id DESC
    LIMIT 100000
)
GROUP BY value
ORDER BY count(value) DESC
LIMIT 20
"""

SELECT_SESSION_PROP_STRING_VALUES_SQL_WITH_FILTER = """
SELECT
    value,
    count(value)
FROM (
    SELECT
        {property_expr} as value
    FROM
        sessions
    WHERE
        team_id = %(team_id)s AND
        {property_expr} ILIKE %(value)s
    ORDER BY session_id DESC
    LIMIT 100000
)
GROUP BY value
ORDER BY count(value) DESC
LIMIT 20
"""
