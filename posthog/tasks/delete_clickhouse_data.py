from typing import List

from posthog.celery import app


@app.task(ignore_result=True, max_retries=1)
def delete_clickhouse_data(team_ids: List[int]) -> None:
    from posthog.models.team import delete_teams_data

    delete_teams_data(team_ids)
