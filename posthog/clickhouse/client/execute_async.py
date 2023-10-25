import hashlib
import json
import time
from dataclasses import asdict as dataclass_asdict
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Optional

from posthog import celery
from clickhouse_driver import Client as SyncClient
from django.conf import settings as app_settings
from statshog.defaults.django import statsd

from posthog import redis
from posthog.celery import enqueue_clickhouse_execute_with_progress
from posthog.clickhouse.client.execute import _prepare_query
from posthog.errors import wrap_query_error
from posthog.settings import (
    CLICKHOUSE_CA,
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_SECURE,
    CLICKHOUSE_USER,
    CLICKHOUSE_VERIFY,
)

REDIS_STATUS_TTL = 600  # 10 minutes


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


def generate_redis_results_key(query_id):
    REDIS_KEY_PREFIX_ASYNC_RESULTS = "query_with_progress"
    key = f"{REDIS_KEY_PREFIX_ASYNC_RESULTS}:{query_id}"
    return key


def execute_with_progress(
    team_id,
    query_id,
    query,
    args=None,
    settings=None,
    with_column_types=False,
    update_freq=0.2,
    task_id=None,
):
    """
    Kick off query with progress reporting
    Iterate over the progress status
    Save status to redis
    Once complete save results to redis
    """

    key = generate_redis_results_key(query_id)
    ch_client = SyncClient(
        host=CLICKHOUSE_HOST,
        database=CLICKHOUSE_DATABASE,
        secure=CLICKHOUSE_SECURE,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        ca_certs=CLICKHOUSE_CA,
        verify=CLICKHOUSE_VERIFY,
        settings={"max_result_rows": "10000"},
    )
    redis_client = redis.get_client()

    start_time = perf_counter()

    prepared_sql, prepared_args, tags = _prepare_query(client=ch_client, query=query, args=args)

    query_status = QueryStatus(team_id, task_id=task_id)

    start_time = time.time()

    try:
        progress = ch_client.execute_with_progress(
            prepared_sql,
            params=prepared_args,
            settings=settings,
            with_column_types=with_column_types,
        )
        for num_rows, total_rows in progress:
            query_status = QueryStatus(
                team_id=team_id,
                num_rows=num_rows,
                total_rows=total_rows,
                complete=False,
                error=False,
                error_message="",
                results=None,
                start_time=start_time,
                task_id=task_id,
            )
            redis_client.set(key, json.dumps(dataclass_asdict(query_status)), ex=REDIS_STATUS_TTL)
            time.sleep(update_freq)
        else:
            rv = progress.get_result()
            query_status = QueryStatus(
                team_id=team_id,
                num_rows=query_status.num_rows,
                total_rows=query_status.total_rows,
                complete=True,
                error=False,
                start_time=query_status.start_time,
                end_time=time.time(),
                error_message="",
                results=rv,
                task_id=task_id,
            )
            redis_client.set(key, json.dumps(dataclass_asdict(query_status)), ex=REDIS_STATUS_TTL)

    except Exception as err:
        err = wrap_query_error(err)
        tags["failed"] = True
        tags["reason"] = type(err).__name__
        statsd.incr("clickhouse_sync_execution_failure")
        query_status = QueryStatus(
            team_id=team_id,
            num_rows=query_status.num_rows,
            total_rows=query_status.total_rows,
            complete=False,
            error=True,
            start_time=query_status.start_time,
            end_time=time.time(),
            error_message=str(err),
            results=None,
            task_id=task_id,
        )
        redis_client.set(key, json.dumps(dataclass_asdict(query_status)), ex=REDIS_STATUS_TTL)

        raise err
    finally:
        ch_client.disconnect()

        execution_time = perf_counter() - start_time

        statsd.timing("clickhouse_sync_execution_time", execution_time * 1000.0)

        if app_settings.SHELL_PLUS_PRINT_SQL:
            print("Execution time: %.6fs" % (execution_time,))  # noqa T201


def enqueue_execute_with_progress(
    team_id,
    query,
    args=None,
    settings=None,
    with_column_types=False,
    bypass_celery=False,
    query_id=None,
    force=False,
):
    if not query_id:
        query_id = _query_hash(query, team_id, args)
    key = generate_redis_results_key(query_id)
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

    # Immediately set status so we don't have race with celery
    query_status = QueryStatus(team_id=team_id, start_time=time.time())
    redis_client.set(key, json.dumps(dataclass_asdict(query_status)), ex=REDIS_STATUS_TTL)

    if bypass_celery:
        # Call directly ( for testing )
        enqueue_clickhouse_execute_with_progress(team_id, query_id, query, args, settings, with_column_types)
    else:
        enqueue_clickhouse_execute_with_progress.delay(team_id, query_id, query, args, settings, with_column_types)

    return query_id


def get_status_or_results(team_id, query_id):
    """
    Returns QueryStatus data class
    QueryStatus data class contains either:
    Current status of running query
    Results of completed query
    Error payload of failed query
    """
    redis_client = redis.get_client()
    key = generate_redis_results_key(query_id)
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


def _query_hash(query: str, team_id: int, args: Any) -> str:
    """
    Takes a query and returns a hex encoded hash of the query and args
    """
    if args:
        key = hashlib.md5((str(team_id) + query + json.dumps(args)).encode("utf-8")).hexdigest()
    else:
        key = hashlib.md5((str(team_id) + query).encode("utf-8")).hexdigest()
    return key
