from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import ch_pool
from posthog.settings import CLICKHOUSE_CLUSTER


ADD_COLUMNS_SHARDED_EVENTS = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS mat_ec_href String DEFAULT extract(elements_chain, '(?::|\")href="(.*?)"'),
ADD COLUMN IF NOT EXISTS mat_ec_texts Array(String) DEFAULT arrayDistinct(extractAll(elements_chain, '(?::|\")text="(.*?)"')),
ADD COLUMN IF NOT EXISTS mat_ec_ids Array(String) DEFAULT arrayDistinct(extractAll(elements_chain, '(?::|\")id="(.*?)"')),
ADD COLUMN IF NOT EXISTS mat_ec_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) DEFAULT arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))
"""

ADD_COLUMNS_EVENTS = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS mat_ec_href String COMMENT 'column_materializer::elements_chain::href',
ADD COLUMN IF NOT EXISTS mat_ec_texts Array(String) COMMENT 'column_materializer::elements_chain::texts',
ADD COLUMN IF NOT EXISTS mat_ec_ids Array(String) COMMENT 'column_materializer::elements_chain::ids',
ADD COLUMN IF NOT EXISTS mat_ec_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) COMMENT 'column_materializer::elements_chain::elements'
"""


def add_columns_to_required_tables(_):
    with ch_pool.get_client() as client:
        client.execute(ADD_COLUMNS_SHARDED_EVENTS.format(table="events", cluster=CLICKHOUSE_CLUSTER))

        client.execute(ADD_COLUMNS_EVENTS.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))


operations = [
    migrations.RunPython(add_columns_to_required_tables),
]
