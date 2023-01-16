from infi.clickhouse_orm import migrations

from posthog.models.element.sql import (
    DISTRIBUTED_ELEMENTS_CHAIN_DAILY_COUNTS_TABLE_SQL,
    ELEMENTS_CHAIN_DAILY_COUNTS_MV_SQL,
    ELEMENTS_CHAIN_DAILY_COUNTS_TABLE_SQL,
)

operations = [
    migrations.RunSQL(ELEMENTS_CHAIN_DAILY_COUNTS_TABLE_SQL()),
    migrations.RunSQL(DISTRIBUTED_ELEMENTS_CHAIN_DAILY_COUNTS_TABLE_SQL()),
    migrations.RunSQL(ELEMENTS_CHAIN_DAILY_COUNTS_MV_SQL()),
]
