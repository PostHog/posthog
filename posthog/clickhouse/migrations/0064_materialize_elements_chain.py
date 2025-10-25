from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import get_client_from_pool
from posthog.settings import CLICKHOUSE_CLUSTER

ADD_COLUMNS_SHARDED_EVENTS = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS elements_chain_href String MATERIALIZED extract(elements_chain, '(?::|\")href="(.*?)"'),
ADD COLUMN IF NOT EXISTS elements_chain_texts Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")text="(.*?)"')),
ADD COLUMN IF NOT EXISTS elements_chain_ids Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")id="(.*?)"')),
ADD COLUMN IF NOT EXISTS elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))
"""

ADD_COLUMNS_EVENTS = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS elements_chain_href String COMMENT 'column_materializer::elements_chain::href',
ADD COLUMN IF NOT EXISTS elements_chain_texts Array(String) COMMENT 'column_materializer::elements_chain::texts',
ADD COLUMN IF NOT EXISTS elements_chain_ids Array(String) COMMENT 'column_materializer::elements_chain::ids',
ADD COLUMN IF NOT EXISTS elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) COMMENT 'column_materializer::elements_chain::elements'
"""


def add_columns_to_required_tables(_):
    with get_client_from_pool() as client:
        client.execute(ADD_COLUMNS_SHARDED_EVENTS.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))

        client.execute(ADD_COLUMNS_EVENTS.format(table="events", cluster=CLICKHOUSE_CLUSTER))


operations = [
    migrations.RunPython(add_columns_to_required_tables),
]
