from django.conf import settings

from posthog.clickhouse.table_engines import (
    Distributed,
    ReplicationScheme,
    MergeTreeEngine,
)

"""
We want to use ML to convert session replay data to embeddings, these will let us check similarity between sessions
and so to cluster sessions. We will store the embeddings in a separate table to the session replay data, so we can
easily iterate on th schema, and so we don't ever have to join recordings data in Postgres and CH

Expected queries will be to load sets of embeddings, by team and date, and to insert embeddings for a session
And to allow us to select sessions by similarity
And to select sessions from session_replay_event which don't have an embedding yet (for processing)
"""

SESSION_REPLAY_EMBEDDINGS_DATA_TABLE = lambda: "sharded_session_replay_embeddings"

SESSION_REPLAY_EMBEDDINGS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    embeddings Array(Float32),
    generation_timestamp DateTime64(6, 'UTC') DEFAULT NOW('UTC'),
    -- we will insert directly for the first test of this
    -- so no _timestamp or _offset column
    --_timestamp SimpleAggregateFunction(max, DateTime)
) ENGINE = {engine}
"""

SESSION_REPLAY_EMBEDDINGS_DATA_TABLE_ENGINE = lambda: MergeTreeEngine(
    "session_replay_embeddings", replication_scheme=ReplicationScheme.SHARDED
)

SESSION_REPLAY_EMBEDDINGS_TABLE_SQL = lambda: (
    SESSION_REPLAY_EMBEDDINGS_TABLE_BASE_SQL
    + """
    PARTITION BY toYYYYMM(generation_timestamp)
    -- order by must be in order of increasing cardinality
    -- so we order by date first, then team_id, then session_id
    -- hopefully, this is a good balance between the two
    ORDER BY (toDate(generation_timestamp), team_id, session_id)
    -- we don't want to keep embeddings forever, so we will set a TTL
    -- the max any individual recording could survive is 1 year, so...
    TTL toDate(generation_timestamp) + INTERVAL 1 YEAR
SETTINGS index_granularity=512
"""
).format(
    table_name=SESSION_REPLAY_EMBEDDINGS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=SESSION_REPLAY_EMBEDDINGS_DATA_TABLE_ENGINE(),
)

# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_session_replay_embeddings based on a sharding key.
WRITABLE_SESSION_REPLAY_EMBEDDINGS_TABLE_SQL = lambda: SESSION_REPLAY_EMBEDDINGS_TABLE_BASE_SQL.format(
    table_name="writable_session_replay_embeddings",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(
        data_table=SESSION_REPLAY_EMBEDDINGS_DATA_TABLE(),
        sharding_key="sipHash64(session_id)",
    ),
)

# This table is responsible for reading from session_replay_embeddings on a cluster setting
DISTRIBUTED_SESSION_REPLAY_EMBEDDINGS_TABLE_SQL = lambda: SESSION_REPLAY_EMBEDDINGS_TABLE_BASE_SQL.format(
    table_name="session_replay_embeddings",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(
        data_table=SESSION_REPLAY_EMBEDDINGS_DATA_TABLE(),
        sharding_key="sipHash64(session_id)",
    ),
)

DROP_SESSION_REPLAY_EMBEDDINGS_TABLE_SQL = lambda: (
    f"DROP TABLE IF EXISTS {SESSION_REPLAY_EMBEDDINGS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)

TRUNCATE_SESSION_REPLAY_EMBEDDINGS_TABLE_SQL = lambda: (
    f"TRUNCATE TABLE IF EXISTS {SESSION_REPLAY_EMBEDDINGS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)
