from infi.clickhouse_orm import migrations

from posthog.client import sync_execute
from posthog.models.instance_setting import get_instance_setting
from posthog.models.session_recording_event.sql import UPDATE_RECORDINGS_TABLE_TTL_SQL


def update_recordings_ttl(_):
    ttl_weeks = get_instance_setting("RECORDINGS_TTL_WEEKS")
    sync_execute(UPDATE_RECORDINGS_TABLE_TTL_SQL(), {"weeks": ttl_weeks})


operations = [
    migrations.RunPython(update_recordings_ttl),
]
