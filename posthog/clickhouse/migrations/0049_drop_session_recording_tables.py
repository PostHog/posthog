from infi.clickhouse_orm import migrations

from posthog.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.settings import CLICKHOUSE_CLUSTER, DEBUG, TEST
import structlog

logger = structlog.get_logger(__name__)

DROP_TABLE_SQL = """
DROP TABLE IF EXISTS {table} ON CLUSTER '{cluster}';
"""


def drop_session_recording_tables(table: str):
    if not is_cloud() and not DEBUG and not TEST:
        logger.debug("Skipping drop_session_recording_tables migration as not on cloud", table=table)
        return
    else:
        sync_execute(DROP_TABLE_SQL.format(table=table, cluster=CLICKHOUSE_CLUSTER))


operations = [
    migrations.RunPython(drop_session_recording_tables("kafka_session_recording_events_partition_statistics")),
    migrations.RunPython(drop_session_recording_tables("kafka_session_recording_events")),
    migrations.RunPython(drop_session_recording_tables("session_recording_events_partition_statistics_mv")),
    migrations.RunPython(drop_session_recording_tables("session_recording_events_mv")),
    migrations.RunPython(drop_session_recording_tables("writable_session_recording_events")),
    migrations.RunPython(drop_session_recording_tables("sharded_session_recording_events")),
    migrations.RunPython(drop_session_recording_tables("session_recording_events")),
]
