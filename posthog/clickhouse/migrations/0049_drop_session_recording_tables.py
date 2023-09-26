import structlog
from django.conf import settings
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.cloud_utils import is_cloud

logger = structlog.get_logger(__name__)

drop_sql_commands = [
    lambda: (f"DROP TABLE IF EXISTS session_recording_events_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    lambda: (
        f"DROP TABLE IF EXISTS session_recording_events_partition_statistics_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
    ),
    lambda: (f"DROP TABLE IF EXISTS kafka_session_recording_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    lambda: (
        f"DROP TABLE IF EXISTS kafka_session_recording_events_partition_statistics ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
    ),
    lambda: (f"DROP TABLE IF EXISTS writable_session_recording_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    lambda: (f"DROP TABLE IF EXISTS sharded_session_recording_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    lambda: (f"DROP TABLE IF EXISTS session_recording_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
]


def no_op_migration(sql: str):
    logger.debug("Skipping drop_session_recording_tables migration as not on cloud, nor in DEBUG or TEST mode", sql=sql)
    # to avoid figuring out why returning a no-op method breaks migrations...
    return run_sql_with_exceptions("SELECT 1")


def run_sql_on_cloud(sql: str):
    if is_cloud() or settings.DEBUG or settings.TEST or settings.E2E_TESTING:
        return run_sql_with_exceptions(sql)
    else:
        return no_op_migration(sql)


operations = [run_sql_on_cloud(sql()) for sql in drop_sql_commands]
