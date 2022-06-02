from infi.clickhouse_orm import migrations

from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER

ADD_COLUMNS_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER '{cluster}'
ADD COLUMN IF NOT EXISTS version UInt64
"""


def add_columns_to_required_tables(_):
    sync_execute(ADD_COLUMNS_BASE_SQL.format(table="cohortpeople", cluster=CLICKHOUSE_CLUSTER))


operations = [
    migrations.RunPython(add_columns_to_required_tables),
]
