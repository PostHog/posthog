from typing import List

from posthog.celery import app
from posthog.models.team.util import delete_teams_clickhouse_data, is_clickhouse_data_cron_enabled


@app.task(ignore_result=True, max_retries=1)
def delete_clickhouse_data(team_ids: List[int]) -> None:
    if not is_clickhouse_data_cron_enabled():
        delete_teams_clickhouse_data(team_ids)
