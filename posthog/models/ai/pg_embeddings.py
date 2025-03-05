from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme


def PG_EMBEDDINGS_DATA_TABLE():
    return "sharded_pg_embeddings"


PG_EMBEDDINGS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    domain String,
    team_id Int64,
    id String,
    vector Array(Float32),
    text String,
    properties VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC') DEFAULT NOW('UTC'),
    is_deleted UInt8,
) ENGINE = {engine}
"""


def PG_EMBEDDINGS_DATA_TABLE_ENGINE():
    return ReplacingMergeTree(
        "pg_embeddings", replication_scheme=ReplicationScheme.SHARDED, ver="timestamp, is_deleted"
    )


def PG_EMBEDDINGS_TABLE_SQL(on_cluster=True):
    return (
        PG_EMBEDDINGS_TABLE_BASE_SQL
        + """
    -- id for uniqueness
    ORDER BY (domain, team_id, id)
    SETTINGS index_granularity=512
    """
    ).format(
        base_sql=PG_EMBEDDINGS_TABLE_BASE_SQL,
        table_name=PG_EMBEDDINGS_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=PG_EMBEDDINGS_DATA_TABLE_ENGINE(),
    )


# Distributed engine tables are only created if CLICKHOUSE_REPLICATED
# This table is responsible for writing to sharded_pg_embeddings based on a sharding key.


def WRITABLE_PG_EMBEDDINGS_TABLE_SQL(on_cluster=True):
    return PG_EMBEDDINGS_TABLE_BASE_SQL.format(
        table_name="writable_pg_embeddings",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=PG_EMBEDDINGS_DATA_TABLE(),
            sharding_key="sipHash64(domain, team_id)",
        ),
        index_clause="",
    )


# This table is responsible for reading from pg_embeddings on a cluster setting
def DISTRIBUTED_PG_EMBEDDINGS_TABLE_SQL(on_cluster=True):
    return PG_EMBEDDINGS_TABLE_BASE_SQL.format(
        table_name="pg_embeddings",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=PG_EMBEDDINGS_DATA_TABLE(),
            sharding_key="sipHash64(domain, team_id)",
        ),
        index_clause="",
    )


def DROP_PG_EMBEDDINGS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PG_EMBEDDINGS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


def TRUNCATE_PG_EMBEDDINGS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {PG_EMBEDDINGS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


INSERT_BULK_PG_EMBEDDINGS_SQL = """
INSERT INTO writable_pg_embeddings (domain, team_id, id, vector, text, properties, is_deleted) VALUES
"""
