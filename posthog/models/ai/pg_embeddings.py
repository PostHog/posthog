from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import ReplacingMergeTree, ReplicationScheme


def PG_EMBEDDINGS_DATA_TABLE():
    return "pg_embeddings"


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
        "pg_embeddings", replication_scheme=ReplicationScheme.REPLICATED, ver="timestamp, is_deleted"
    )


def PG_EMBEDDINGS_TABLE_SQL(on_cluster=True):
    return (
        PG_EMBEDDINGS_TABLE_BASE_SQL
        + """
    -- id for uniqueness
    ORDER BY (team_id, domain, id)
    SETTINGS index_granularity=512
    """
    ).format(
        table_name=PG_EMBEDDINGS_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=PG_EMBEDDINGS_DATA_TABLE_ENGINE(),
    )


def DROP_PG_EMBEDDINGS_TABLE_SQL(on_cluster=True):
    return f"DROP TABLE IF EXISTS {PG_EMBEDDINGS_DATA_TABLE()} {ON_CLUSTER_CLAUSE(on_cluster)}"


def TRUNCATE_PG_EMBEDDINGS_TABLE_SQL(on_cluster=True):
    return f"TRUNCATE TABLE IF EXISTS {PG_EMBEDDINGS_DATA_TABLE()} {ON_CLUSTER_CLAUSE(on_cluster)}"


PG_EMBEDDINGS_COLUMNS = ("domain", "team_id", "id", "vector", "text", "properties", "is_deleted")


def _insert_bulk_sql(columns: tuple[str, ...]) -> str:
    return f"\nINSERT INTO {PG_EMBEDDINGS_DATA_TABLE()} ({', '.join(columns)}) VALUES\n"


INSERT_BULK_PG_EMBEDDINGS_SQL = _insert_bulk_sql(PG_EMBEDDINGS_COLUMNS)
INSERT_BULK_PG_EMBEDDINGS_WITH_TIMESTAMP_SQL = _insert_bulk_sql((*PG_EMBEDDINGS_COLUMNS, "timestamp"))
