from infi.clickhouse_orm import migrations

from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER

DROP_TABLE_SQL = """
DROP TABLE IF EXISTS {table} ON CLUSTER '{cluster}';
"""

tables = [
    "kafka_session_recording_events_partition_statistics",
    "kafka_session_recording_events",
    "session_recording_events_partition_statistics_mv",
    "session_recording_events_mv",
    "writable_session_recording_events",
    "sharded_session_recording_events",
    "session_recording_events",
]


def drop_session_recording_tables(_):
    for table in tables:
        sync_execute(DROP_TABLE_SQL.format(table=table, cluster=CLICKHOUSE_CLUSTER))


operations = [
    migrations.RunPython(drop_session_recording_tables),
]
