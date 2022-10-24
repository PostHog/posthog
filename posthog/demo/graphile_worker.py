import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

from django.db import connection

BULK_INSERT_JOBS_SQL = """
    INSERT INTO graphile_worker.jobs (task_identifier, payload, run_at, max_attempts, flags) VALUES {values}"""

COPY_GRAPHILE_WORKER_JOBS_BETWEEN_TEAMS_SQL = """
    INSERT INTO graphile_worker.jobs (task_identifier, payload, run_at, max_attempts, flags)
    SELECT
        task_identifier, jsonb_set(payload::jsonb, '{ eventPayload, team_id }', to_jsonb(%(target_team_id)s))::json,
        run_at, max_attempts, '{ "team_id": %(target_team_id)s }'::jsonb
    FROM graphile_worker.jobs WHERE (flags->'team_id')::int = %(source_team_id)s"""

ERASE_GRAPHILE_JOBS_OF_TEAM_SQL = """DELETE FROM graphile_worker.jobs WHERE (flags->'team_id')::int = %(team_id)s"""


@dataclass
class GraphileWorkerJob:
    task_identifier: str
    payload: Dict[str, Any]
    run_at: dt.datetime
    max_attempts: int = field(default=1)
    flags: Optional[Dict[str, Any]] = field(default=None)


def _execute_graphile_worker_query(query: str, params: Optional[Union[List[Any], Dict[str, Any]]] = None):
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, params=params)
    except Exception as e:
        if 'relation "graphile_worker.jobs" does not exist' in str(e):
            raise Exception("The plugin server must be started before trying to save future demo data") from e
        raise e


def bulk_queue_graphile_worker_jobs(jobs: Sequence[GraphileWorkerJob]):
    """Bulk-insert jobs into the graphile_worker.jobs table.

    This is a bit dirty and only intended for demo data, not production.
    """
    values: List[str] = []
    params: List[Any] = []
    for job in jobs:
        values.append("(%s, %s::json, %s::timestamptz, %s, %s::jsonb)")
        params.append(job.task_identifier)
        params.append(json.dumps(job.payload))
        params.append(job.run_at.isoformat())
        params.append(job.max_attempts)
        params.append(json.dumps(job.flags) if job.flags else None)
    _execute_graphile_worker_query(BULK_INSERT_JOBS_SQL.format(values=", ".join(values)), params=params)


def copy_graphile_worker_jobs_between_teams(source_team_id: int, target_team_id: int):
    """Copy all scheduled demo events between projects.

    This is a bit dirty and only intended for demo data, not production.
    """
    _execute_graphile_worker_query(
        COPY_GRAPHILE_WORKER_JOBS_BETWEEN_TEAMS_SQL,
        {"target_team_id": target_team_id, "source_team_id": source_team_id},
    )


def erase_graphile_worker_jobs_for_team(team_id: int):
    """Erase all scheduled demo events of project.

    This is a bit dirty and only intended for demo data, not production.
    """
    _execute_graphile_worker_query(ERASE_GRAPHILE_JOBS_OF_TEAM_SQL, {"team_id": team_id})
