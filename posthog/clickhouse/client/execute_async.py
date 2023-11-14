import json
import uuid

import structlog
import time
from dataclasses import asdict as dataclass_asdict
from dataclasses import dataclass
from typing import Any, Optional

from posthog import celery

from posthog import redis
from posthog.celery import process_query_task
from posthog.clickhouse.query_tagging import tag_queries

logger = structlog.get_logger(__name__)

REDIS_STATUS_TTL = 600  # 10 minutes
REDIS_KEY_PREFIX_ASYNC_RESULTS = "query_async"


@dataclass
class QueryStatus:
    team_id: int
    num_rows: float = 0
    total_rows: float = 0
    error: bool = False
    complete: bool = False
    error_message: str = ""
    results: Any = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    task_id: Optional[str] = None


def generate_redis_results_key(query_id: str, team_id: int) -> str:
    return f"{REDIS_KEY_PREFIX_ASYNC_RESULTS}:{team_id}:{query_id}"


def execute_process_query(
    team_id,
    query_id,
    query_json,
    in_export_context,
    refresh_requested,
    task_id=None,
):
    """
    Kick off query
    Once complete save results to redis
    """

    key = generate_redis_results_key(query_id, team_id)
    redis_client = redis.get_client()

    query_status = QueryStatus(team_id, task_id=task_id)

    from posthog.models import Team
    from posthog.api.process import process_query

    team = Team.objects.get(pk=team_id)

    try:
        tag_queries(client_query_id=query_id, team_id=team_id)
        results = process_query(
            team=team, query_json=query_json, in_export_context=in_export_context, refresh_requested=refresh_requested
        )
        logger.info("Got results for team %s query %s", team_id, query_id)
        query_status = QueryStatus(
            team_id=team_id,
            complete=True,
            error=False,
            error_message="",
            results=results,
            task_id=task_id,
        )
        redis_client.set(key, json.dumps(dataclass_asdict(query_status)), ex=REDIS_STATUS_TTL)
    except Exception as err:
        query_status = QueryStatus(
            team_id=team_id,
            complete=False,
            error=True,
            error_message=str(err),
            results=None,
            task_id=task_id,
        )
        raise err
    finally:
        redis_client.set(key, json.dumps(dataclass_asdict(query_status)), ex=REDIS_STATUS_TTL)


def enqueue_process_query_task(
    team_id,
    query_json,
    query_id=None,
    refresh_requested=False,
    in_export_context=False,
    bypass_celery=False,
    force=False,
):
    if not query_id:
        query_id = uuid.uuid4().hex

    key = generate_redis_results_key(query_id, team_id)
    redis_client = redis.get_client()

    if force:
        # If we want to force rerun of this query we need to
        # 1) Get the current status from redis
        task_str = redis_client.get(key)
        if task_str:
            # if the status exists in redis we need to tell celery to kill the job
            task_str = task_str.decode("utf-8")
            query_task = QueryStatus(**json.loads(task_str))
            # Instruct celery to revoke task and terminate if running
            celery.app.control.revoke(query_task.task_id, terminate=True)
            # Then we need to make redis forget about this job entirely
            # and continue as normal. As if we never saw this query before
            redis_client.delete(key)

    if redis_client.get(key):
        # If we've seen this query before return the query_id and don't resubmit it.
        return query_id

    # Immediately set status, so we don't have race with celery
    query_status = QueryStatus(team_id=team_id, start_time=time.time())
    redis_client.set(key, json.dumps(dataclass_asdict(query_status)), ex=REDIS_STATUS_TTL)

    if bypass_celery:
        # Call directly ( for testing )
        process_query_task(
            team_id, query_id, query_json, in_export_context=in_export_context, refresh_requested=refresh_requested
        )
    else:
        process_query_task.delay(
            team_id, query_id, query_json, in_export_context=in_export_context, refresh_requested=refresh_requested
        )

    return query_id


def get_query_status(team_id, query_id):
    """
    Returns QueryStatus data class
    QueryStatus data class contains either:
    Current status of running query
    Results of completed query
    Error payload of failed query
    """
    redis_client = redis.get_client()
    key = generate_redis_results_key(query_id, team_id)
    try:
        byte_results = redis_client.get(key)
        if byte_results:
            str_results = byte_results.decode("utf-8")
        else:
            return QueryStatus(team_id, error=True, error_message="Query is unknown to backend")
        query_status = QueryStatus(**json.loads(str_results))
        if query_status.team_id != team_id:
            raise Exception("Requesting team is not executing team")
    except Exception as e:
        query_status = QueryStatus(team_id, error=True, error_message=str(e))
    return query_status


def cancel_query(team_id, query_id):
    query_status = get_query_status(team_id, query_id)

    if query_status.task_id:
        celery.app.control.revoke(query_status.task_id, terminate=True)

        from posthog.api.process import cancel_query_on_cluster

        cancel_query_on_cluster(team_id, query_id)

    redis_client = redis.get_client()
    key = generate_redis_results_key(query_id, team_id)
    redis_client.delete(key)

    return True
