from temporalio import activity

from posthog.clickhouse.client.execute import resolve_kill_switch_level
from posthog.sync import database_sync_to_async_pool


@activity.defn
async def get_clickhouse_kill_switch_level_activity(team_id: int) -> str:
    level = await database_sync_to_async_pool(resolve_kill_switch_level)(team_id)
    return level.value
