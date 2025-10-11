from django.conf import settings

from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree
from posthog.kafka_client.topics import (
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_EMBEDDINGS,
)

#
# error_tracking_issue_fingerprint_overrides: This table contains rows for all (team_id, fingerprint)
# pairs where the $exception_issue_id has changed.
#

ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE = "error_tracking_issue_fingerprint_overrides"

ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    team_id Int64,
    fingerprint VARCHAR,
    issue_id UUID,
    is_deleted Int8,
    version Int64
    {extra_fields}
) ENGINE = {engine}
"""

ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_ENGINE = lambda: ReplacingMergeTree(
    ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE, ver="version"
)

ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL = lambda: (
    ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_BASE_SQL
    + """
    ORDER BY (team_id, fingerprint)
    SETTINGS index_granularity = 512
    """
).format(
    table_name=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE,
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_ENGINE(),
    extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    , {index_by_kafka_timestamp(ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE)}
    """,
)

KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL = (
    lambda: ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_BASE_SQL.format(
        table_name="kafka_" + ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE,
        cluster=settings.CLICKHOUSE_CLUSTER,
        engine=kafka_engine(
            KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT, group="clickhouse-error-tracking-issue-fingerprint-overrides"
        ),
        extra_fields="",
    )
)


def ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name}_mv ON CLUSTER '{cluster}'
TO {database}.{table_name}
AS SELECT
team_id,
fingerprint,
issue_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM {database}.kafka_{table_name}
WHERE version > 0 -- only store updated rows, not newly inserted ones
""".format(
        table_name=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE,
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
    )


def TRUNCATE_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"


INSERT_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES = """
INSERT INTO error_tracking_issue_fingerprint_overrides (fingerprint, issue_id, team_id, is_deleted, version, _timestamp, _offset, _partition) SELECT %(fingerprint)s, %(issue_id)s, %(team_id)s, %(is_deleted)s, %(version)s, now(), 0, 0 VALUES
"""


ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE = "error_tracking_issue_fingerprint_embeddings"
ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE = f"writable_{ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE}"
KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE = f"kafka_{ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE}"
ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_MV = f"{ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE}_mv"

ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    model_name LowCardinality(String),
    embedding_version Int64, -- This is the given iteration of the embedding approach - it will /probably/ always be 0, but we want to be able to iterate on e.g. what we feed the model, so we'll leave that door open for now
    fingerprint VARCHAR,
    inserted_at DateTime64(3, 'UTC'),
    embeddings Array(Float64) -- We could experiment with quantization, but if we do we can use a new column, for now we'll eat the inefficiency
    {extra_fields} -- Unused, I think, but the above has it, so
) ENGINE = {engine}
"""


def ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_ENGINE():
    return ReplacingMergeTree(ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE, ver="inserted_at")


def ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_SQL():
    return (
        ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_BASE_SQL
        + """
    ORDER BY (team_id, model_name, embedding_version, fingerprint)
    SETTINGS index_granularity = 512
    """
    ).format(
        table_name=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE,
        engine=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_ENGINE(),
        extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    , {index_by_kafka_timestamp(ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE)}
    """,
    )


def ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE_SQL():
    return ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_BASE_SQL.format(
        table_name=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE,
        engine=Distributed(
            data_table=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE,
            cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    )


def KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_SQL():
    return ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_BASE_SQL.format(
        table_name=KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE,
        engine=kafka_engine(
            KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_EMBEDDINGS, group="clickhouse_error_tracking_fingerprint_embeddings"
        ),
        extra_fields="",
    )


def ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_MV_SQL(
    target_table=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE,
):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {target_table}
AS SELECT
team_id,
model_name,
embedding_version,
fingerprint,
_timestamp as inserted_at,
embeddings,
_timestamp,
_offset,
_partition
FROM {database}.{kafka_table}
""".format(
        mv_name=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_MV,
        target_table=target_table,
        kafka_table=KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE,
        database=settings.CLICKHOUSE_DATABASE,
    )


def TRUNCATE_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
