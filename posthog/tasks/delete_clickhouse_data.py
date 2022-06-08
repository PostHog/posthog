from typing import List

from posthog.celery import app
from posthog.models.team.util import delete_teams_clickhouse_data


@app.task(ignore_result=True, max_retries=1)
def delete_clickhouse_data(team_ids: List[int]) -> None:

    delete_teams_clickhouse_data(team_ids)
