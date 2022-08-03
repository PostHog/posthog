import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from django.db import connection

BULK_INSERT_JOBS_SQL = """
    INSERT INTO graphile_worker.jobs (task_identifier, payload, run_at, max_attempts, flags) VALUES {values}"""

COPY_GRAPHILE_JOBS_BETWEEN_TEAMS_SQL = """
    INSERT INTO graphile_worker.jobs (task_identifier, payload, run_at, max_attempts, flags)
    SELECT
        task_identifier, jsonb_set(payload::jsonb, '{ eventPayload, team_id }', to_jsonb(%(target_team_id)s))::json,
        run_at, max_attempts, '{ "team_id": %(target_team_id)s }'::jsonb
    FROM graphile_worker.jobs WHERE (flags->'team_id')::int = %(source_team_id)s"""


@dataclass
class GraphileJob:
    task_identifier: str
    payload: Dict[str, Any]
    run_at: dt.datetime
    max_attempts: int = field(default=1)
    flags: Optional[Dict[str, Any]] = field(default=None)


def bulk_queue_graphile_jobs(jobs: Sequence[GraphileJob]):
    values: List[str] = []
    params: List[Any] = []
    for job in jobs:
        values.append("(%s, %s::json, %s::timestamptz, %s, %s::jsonb)")
        params.append(job.task_identifier)
        params.append(json.dumps(job.payload))
        params.append(job.run_at.isoformat())
        params.append(job.max_attempts)
        params.append(json.dumps(job.flags) if job.flags else None)
    with connection.cursor() as cursor:
        cursor.execute(BULK_INSERT_JOBS_SQL.format(values=", ".join(values)), params=params)


def copy_graphile_jobs_between_teams(source_team_id: int, target_team_id: int):
    with connection.cursor() as cursor:
        cursor.execute(
            COPY_GRAPHILE_JOBS_BETWEEN_TEAMS_SQL, {"target_team_id": target_team_id, "source_team_id": source_team_id},
        )
