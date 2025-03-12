from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import get_client_from_pool
from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.settings import CLICKHOUSE_CLUSTER


ADD_COLUMNS_SHARDED_EVENTS = f"""
ALTER TABLE {{table}} ON CLUSTER {{cluster}}
ADD COLUMN IF NOT EXISTS $session_id_uuid Nullable(UInt128) MATERIALIZED toUInt128(accurateCastOrNull({trim_quotes_expr("JSONExtractRaw(properties, '$session_id')")}, 'UUID'))
"""

ADD_COLUMNS_EVENTS = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS $session_id_uuid Nullable(UInt128) COMMENT 'column_materializer::$session_id_uuid'
"""


def add_columns_to_required_tables(_):
    with get_client_from_pool() as client:
        client.execute(ADD_COLUMNS_SHARDED_EVENTS.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))
        client.execute(ADD_COLUMNS_EVENTS.format(table="events", cluster=CLICKHOUSE_CLUSTER))


operations = [
    migrations.RunPython(add_columns_to_required_tables),
]
