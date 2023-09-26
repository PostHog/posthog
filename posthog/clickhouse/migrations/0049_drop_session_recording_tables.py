import structlog

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.cloud_utils import is_cloud
from posthog.session_recordings.sql.session_recording_event_sql import (
    DEPRECATE_CH_RECORDINGS_DROP_SESSION_RECORDING_EVENTS_MV_TABLE_SQL,
    DEPRECATE_CH_RECORDINGS_DROP_SESSION_RECORDING_EVENTS_PARTITION_STATISTICS_MV_TABLE_SQL,
    DEPRECATE_CH_RECORDINGS_DROP_KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL,
    DEPRECATE_CH_RECORDINGS_DROP_KAFKA_SESSION_RECORDING_EVENTS_PARTITION_STATISTICS_TABLE_SQL,
    DEPRECATE_CH_RECORDINGS_DROP_WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL,
    DEPRECATE_CH_RECORDINGS_DROP_SHARDED_SESSION_RECORDING_EVENTS_TABLE_SQL,
    DEPRECATE_CH_RECORDINGS_DROP_SESSION_RECORDING_EVENTS_TABLE_SQL,
)
from posthog.settings import DEBUG, TEST

logger = structlog.get_logger(__name__)


def no_op_migration(sql: str):
    logger.debug("Skipping drop_session_recording_tables migration as not on cloud", sql=sql)


def run_sql_on_cloud(sql: str) -> None:
    if is_cloud() or DEBUG or TEST:
        return run_sql_with_exceptions(sql)
    else:
        return no_op_migration(sql)


operations = [
    run_sql_on_cloud(DEPRECATE_CH_RECORDINGS_DROP_SESSION_RECORDING_EVENTS_MV_TABLE_SQL()),
    run_sql_on_cloud(DEPRECATE_CH_RECORDINGS_DROP_SESSION_RECORDING_EVENTS_PARTITION_STATISTICS_MV_TABLE_SQL()),
    run_sql_on_cloud(DEPRECATE_CH_RECORDINGS_DROP_KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL()),
    run_sql_on_cloud(DEPRECATE_CH_RECORDINGS_DROP_KAFKA_SESSION_RECORDING_EVENTS_PARTITION_STATISTICS_TABLE_SQL()),
    run_sql_on_cloud(DEPRECATE_CH_RECORDINGS_DROP_WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL()),
    run_sql_on_cloud(DEPRECATE_CH_RECORDINGS_DROP_SHARDED_SESSION_RECORDING_EVENTS_TABLE_SQL()),
    run_sql_on_cloud(DEPRECATE_CH_RECORDINGS_DROP_SESSION_RECORDING_EVENTS_TABLE_SQL()),
]
