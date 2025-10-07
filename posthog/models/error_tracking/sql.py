from django.conf import settings

from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT

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
