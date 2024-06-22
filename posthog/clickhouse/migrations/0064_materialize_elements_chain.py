from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import ch_pool
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    EVENTS_TABLE_JSON_MV_SQL,
    KAFKA_EVENTS_TABLE_JSON_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER


# KafkaEngine doesn't support DEFAULT/MATERIALIZED/EPHEMERAL expressions for columns, so we're
# leaning on the default of 0 to be "full" (as desired)
ADD_COLUMNS_BASE_SQL = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS elements_chain_mat_href String MATERIALIZED extract(elements_chain, '(?::|\")href="(.*?)"'),
ADD COLUMN IF NOT EXISTS elements_chain_mat_texts Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")text="(.*?)"')),
ADD COLUMN IF NOT EXISTS elements_chain_mat_ids Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")id="(.*?)"')),
ADD COLUMN IF NOT EXISTS elements_chain_mat_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))
"""


def add_columns_to_required_tables(_):
    with ch_pool.get_client() as client:
        client.execute(ADD_COLUMNS_BASE_SQL.format(table="events", cluster=CLICKHOUSE_CLUSTER))

        client.execute(ADD_COLUMNS_BASE_SQL.format(table="writable_events", cluster=CLICKHOUSE_CLUSTER))
        client.execute(ADD_COLUMNS_BASE_SQL.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))


operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS events_json_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_events_json ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunPython(add_columns_to_required_tables),
    run_sql_with_exceptions(KAFKA_EVENTS_TABLE_JSON_SQL()),
    run_sql_with_exceptions(EVENTS_TABLE_JSON_MV_SQL()),
]
