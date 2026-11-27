from infi.clickhouse_orm import migrations

from posthog.clickhouse.client import sync_execute
from posthog.models.performance.sql import UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL


def update_performance_events_ttl(database):
    sync_execute(
        UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL(),
        {"weeks": 3},
    )


operations = [migrations.RunPython(update_performance_events_ttl)]
