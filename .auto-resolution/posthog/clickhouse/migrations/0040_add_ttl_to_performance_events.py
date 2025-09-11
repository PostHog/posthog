from infi.clickhouse_orm import migrations

from posthog.clickhouse.client import sync_execute
from posthog.models.performance.sql import UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL
from posthog.settings import CONSTANCE_CONFIG


def update_performance_events_ttl(database):
    sync_execute(
        UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL(),
        {"weeks": CONSTANCE_CONFIG["RECORDINGS_PERFORMANCE_EVENTS_TTL_WEEKS"][0]},
    )


operations = [migrations.RunPython(update_performance_events_ttl)]
