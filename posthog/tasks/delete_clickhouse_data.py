from typing import List

from posthog.celery import app
from posthog.utils import is_clickhouse_enabled


@app.task(ignore_result=True, max_retries=1)
def delete_clickhouse_data(team_ids: List[int]) -> None:
    if is_clickhouse_enabled():
        from ee.clickhouse.models.team import delete_teams_data

        delete_teams_data(team_ids)
