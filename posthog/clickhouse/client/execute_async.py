import datetime
import json
import uuid

import structlog
from rest_framework.exceptions import NotFound

from posthog import celery, redis
from posthog.celery import process_query_task
from posthog.clickhouse.query_tagging import tag_queries
from posthog.schema import QueryStatus

logger = structlog.get_logger(__name__)

REDIS_STATUS_TTL_SECONDS = 600  # 10 minutes
REDIS_KEY_PREFIX_ASYNC_RESULTS = "query_async"


class QueryNotFoundError(NotFound):
    pass


class QueryRetrievalError(Exception):
    pass


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
    key = generate_redis_results_key(query_id, team_id)
    redis_client = redis.get_client()

    from posthog.models import Team
    from posthog.api.services.query import process_query

    team = Team.objects.get(pk=team_id)

    query_status = QueryStatus(
        id=query_id,
        team_id=team_id,
        task_id=task_id,
        complete=False,
        error=True,  # Assume error in case nothing below ends up working
        start_time=datetime.datetime.utcnow(),
    )
    value = query_status.model_dump_json()

    try:
        tag_queries(client_query_id=query_id, team_id=team_id)
        results = process_query(
            team=team, query_json=query_json, in_export_context=in_export_context, refresh_requested=refresh_requested
        )
        logger.info("Got results for team %s query %s", team_id, query_id)
        query_status.complete = True
        query_status.error = False
        query_status.results = results
        query_status.expiration_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=REDIS_STATUS_TTL_SECONDS)
        query_status.end_time = datetime.datetime.utcnow()
        value = query_status.model_dump_json()
    except Exception as err:
        query_status.results = None  # Clear results in case they are faulty
        query_status.error_message = str(err)
        logger.error("Error processing query for team %s query %s: %s", team_id, query_id, err)
        value = query_status.model_dump_json()
        raise err
    finally:
        redis_client.set(key, value, ex=REDIS_STATUS_TTL_SECONDS)


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
    query_status = QueryStatus(id=query_id, team_id=team_id)
    redis_client.set(key, query_status.model_dump_json(), ex=REDIS_STATUS_TTL_SECONDS)

    if bypass_celery:
        # Call directly ( for testing )
        process_query_task(
            team_id, query_id, query_json, in_export_context=in_export_context, refresh_requested=refresh_requested
        )
    else:
        task = process_query_task.delay(
            team_id, query_id, query_json, in_export_context=in_export_context, refresh_requested=refresh_requested
        )
        query_status.task_id = task.id
        redis_client.set(key, query_status.model_dump_json(), ex=REDIS_STATUS_TTL_SECONDS)

    return query_id


def get_query_status(team_id, query_id):
    redis_client = redis.get_client()
    key = generate_redis_results_key(query_id, team_id)

    try:
        byte_results = redis_client.get(key)
    except Exception as e:
        raise QueryRetrievalError(f"Error retrieving query {query_id} for team {team_id}") from e

    if not byte_results:
        raise QueryNotFoundError(f"Query {query_id} not found for team {team_id}")

    return QueryStatus(**json.loads(byte_results))


def cancel_query(team_id, query_id):
    query_status = get_query_status(team_id, query_id)

    if query_status.task_id:
        logger.info("Got task id %s, attempting to revoke", query_status.task_id)
        celery.app.control.revoke(query_status.task_id, terminate=True)

        from posthog.clickhouse.cancel import cancel_query_on_cluster

        logger.info("Revoked task id %s, attempting to cancel on cluster", query_status.task_id)
        cancel_query_on_cluster(team_id, query_id)

    redis_client = redis.get_client()
    key = generate_redis_results_key(query_id, team_id)
    logger.info("Deleting redis query key %s", key)
    redis_client.delete(key)

    return True
