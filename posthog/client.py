import hashlib
import json
import time
import types
from dataclasses import dataclass
from time import perf_counter
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
    cast,
)

import sqlparse
from celery.task.control import revoke
from clickhouse_driver import Client as SyncClient
from clickhouse_pool import ChPool
from dataclasses_json import dataclass_json
from django.conf import settings as app_settings

from posthog import redis
from posthog.celery import enqueue_clickhouse_execute_with_progress
from posthog.errors import wrap_query_error
from posthog.internal_metrics import incr, timing
from posthog.settings import (
    CLICKHOUSE_CA,
    CLICKHOUSE_CONN_POOL_MAX,
    CLICKHOUSE_CONN_POOL_MIN,
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_SECURE,
    CLICKHOUSE_USER,
    CLICKHOUSE_VERIFY,
    TEST,
)
from posthog.timer import get_timer_thread

InsertParams = Union[list, tuple, types.GeneratorType]
NonInsertParams = Dict[str, Any]
QueryArgs = Optional[Union[InsertParams, NonInsertParams]]

CACHE_TTL = 60  # seconds
SLOW_QUERY_THRESHOLD_MS = 15000
QUERY_TIMEOUT_THREAD = get_timer_thread("posthog.client", SLOW_QUERY_THRESHOLD_MS)

_request_information: Optional[Dict] = None


# Optimize_move_to_prewhere setting is set because of this regression test
# test_ilike_regression_with_current_clickhouse_version
# https://github.com/PostHog/posthog/blob/master/ee/clickhouse/queries/test/test_trends.py#L1566
settings_override = {"optimize_move_to_prewhere": 0}


def default_client():
    """
    Return a bare bones client for use in places where we are only interested in general ClickHouse state
    DO NOT USE THIS FOR QUERYING DATA
    """
    return SyncClient(
        host=CLICKHOUSE_HOST,
        # We set "system" here as we don't necessarily have a "default" database,
        # which is what the clickhouse_driver would use by default. We are
        # assuming that this exists and we have permissions to access it. This
        # feels like a reasonably safe assumption as e.g. we already reference
        # `system.numbers` in multiple places within queries. We also assume
        # access to various other tables e.g. to handle async migrations.
        database="system",
        secure=CLICKHOUSE_SECURE,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        ca_certs=CLICKHOUSE_CA,
        verify=CLICKHOUSE_VERIFY,
    )


def make_ch_pool(**overrides) -> ChPool:
    kwargs = {
        "host": CLICKHOUSE_HOST,
        "database": CLICKHOUSE_DATABASE,
        "secure": CLICKHOUSE_SECURE,
        "user": CLICKHOUSE_USER,
        "password": CLICKHOUSE_PASSWORD,
        "ca_certs": CLICKHOUSE_CA,
        "verify": CLICKHOUSE_VERIFY,
        "connections_min": CLICKHOUSE_CONN_POOL_MIN,
        "connections_max": CLICKHOUSE_CONN_POOL_MAX,
        "settings": {"mutations_sync": "1"} if TEST else {},
        # Without this, OPTIMIZE table and other queries will regularly run into timeouts
        "send_receive_timeout": 30 if TEST else 999_999_999,
        **overrides,
    }

    return ChPool(**kwargs)


ch_client = SyncClient(
    host=CLICKHOUSE_HOST,
    database=CLICKHOUSE_DATABASE,
    secure=CLICKHOUSE_SECURE,
    user=CLICKHOUSE_USER,
    password=CLICKHOUSE_PASSWORD,
    ca_certs=CLICKHOUSE_CA,
    verify=CLICKHOUSE_VERIFY,
    settings={"mutations_sync": "1"} if TEST else {},
)

ch_pool = make_ch_pool()


def async_execute(query, args=None, settings=None, with_column_types=False):
    return sync_execute(query, args, settings=settings, with_column_types=with_column_types)


def cache_sync_execute(query, args=None, redis_client=None, ttl=CACHE_TTL, settings=None, with_column_types=False):
    if not redis_client:
        redis_client = redis.get_client()
    key = _key_hash(query, args)
    if redis_client.exists(key):
        result = _deserialize(redis_client.get(key))
        return result
    else:
        result = sync_execute(query, args, settings=settings, with_column_types=with_column_types)
        redis_client.set(key, _serialize(result), ex=ttl)
        return result


def sync_execute(query, args=None, settings=None, with_column_types=False, flush=True):
    if TEST and flush:
        try:
            from posthog.test.base import flush_persons_and_events

            flush_persons_and_events()
        except ModuleNotFoundError:  # when we run plugin server tests it tries to run above, ignore
            pass

    with ch_pool.get_client() as client:
        start_time = perf_counter()

        prepared_sql, prepared_args, tags = _prepare_query(client=client, query=query, args=args)

        timeout_task = QUERY_TIMEOUT_THREAD.schedule(_notify_of_slow_query_failure, tags)

        settings = {**settings_override, **(settings or {})}

        try:
            result = client.execute(
                prepared_sql, params=prepared_args, settings=settings, with_column_types=with_column_types,
            )
        except Exception as err:
            err = wrap_query_error(err)
            tags["failed"] = True
            tags["reason"] = type(err).__name__
            incr("clickhouse_sync_execution_failure", tags=tags)

            raise err
        finally:
            execution_time = perf_counter() - start_time

            QUERY_TIMEOUT_THREAD.cancel(timeout_task)
            timing("clickhouse_sync_execution_time", execution_time * 1000.0, tags=tags)

            if app_settings.SHELL_PLUS_PRINT_SQL:
                print("Execution time: %.6fs" % (execution_time,))
    return result


def query_with_columns(
    query: str,
    args: Optional[QueryArgs] = None,
    columns_to_remove: Optional[Sequence[str]] = None,
    columns_to_rename: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    if columns_to_remove is None:
        columns_to_remove = []
    if columns_to_rename is None:
        columns_to_rename = {}
    metrics, types = sync_execute(query, args, with_column_types=True)
    type_names = [key for key, _type in types]

    rows = []
    for row in metrics:
        result = {}
        for type_name, value in zip(type_names, row):
            if isinstance(value, list):
                value = ", ".join(map(str, value))
            if type_name not in columns_to_remove:
                result[columns_to_rename.get(type_name, type_name)] = value

        rows.append(result)

    return rows


REDIS_STATUS_TTL = 600  # 10 minutes


@dataclass_json
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
    team_id, query_id, query, args=None, settings=None, with_column_types=False, update_freq=0.2, task_id=None
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

    timeout_task = QUERY_TIMEOUT_THREAD.schedule(_notify_of_slow_query_failure, tags)

    query_status = QueryStatus(team_id, task_id=task_id)

    start_time = time.time()

    try:
        progress = ch_client.execute_with_progress(
            prepared_sql, params=prepared_args, settings=settings, with_column_types=with_column_types,
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
            redis_client.set(key, query_status.to_json(), ex=REDIS_STATUS_TTL)  # type: ignore
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
            redis_client.set(key, query_status.to_json(), ex=REDIS_STATUS_TTL)  # type: ignore

    except Exception as err:
        err = wrap_query_error(err)
        tags["failed"] = True
        tags["reason"] = type(err).__name__
        incr("clickhouse_sync_execution_failure", tags=tags)
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
        redis_client.set(key, query_status.to_json(), ex=REDIS_STATUS_TTL)  # type: ignore

        raise err
    finally:
        execution_time = perf_counter() - start_time

        QUERY_TIMEOUT_THREAD.cancel(timeout_task)
        timing("clickhouse_sync_execution_time", execution_time * 1000.0, tags=tags)

        if app_settings.SHELL_PLUS_PRINT_SQL:
            print("Execution time: %.6fs" % (execution_time,))


def enqueue_execute_with_progress(
    team_id, query, args=None, settings=None, with_column_types=False, bypass_celery=False, query_id=None, force=False
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
            query_task = QueryStatus.from_json(task_str)  # type: ignore
            # Instruct celery to revoke task and terminate if running
            revoke(query_task.task_id, terminate=True)
            # Then we need to make redis forget about this job entirely
            # and continue as normal. As if we never saw this query before
            redis_client.delete(key)

    if redis_client.get(key):
        # If we've seen this query before return the query_id and don't resubmit it.
        return query_id

    # Immediately set status so we don't have race with celery
    query_status = QueryStatus(team_id=team_id, start_time=time.time())
    redis_client.set(key, query_status.to_json(), ex=REDIS_STATUS_TTL)  # type: ignore

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
        query_status = QueryStatus.from_json(str_results)  # type: ignore
        if query_status.team_id != team_id:
            raise Exception("Requesting team is not executing team")
    except Exception as e:
        query_status = QueryStatus(team_id, error=True, error_message=str(e))
    return query_status


def substitute_params(query, params):
    """
    Helper method to ease rendering of sql clickhouse queries progressively.
    For example, there are many places where we construct queries to be used
    as subqueries of others. Each time we generate a subquery we also pass
    up the "bound" parameters to be used to render the query, which
    otherwise only happens at the point of calling clickhouse via the
    clickhouse_driver `Client`.

    This results in sometimes large lists of parameters with no relevance to
    the containing query being passed up. Rather than do this, we can
    instead "render" the subqueries prior to using as a subquery, so our
    containing code is only responsible for it's parameters, and we can
    avoid any potential param collisions.
    """
    return cast(SyncClient, ch_client).substitute_params(query, params)


def _prepare_query(client: SyncClient, query: str, args: QueryArgs):
    """
    Given a string query with placeholders we do one of two things:

        1. for a insert query we just format, and remove comments
        2. for non-insert queries, we return the sql with placeholders
        evaluated with the contents of `args`

    We also return `tags` which contains some detail around the context
    within which the query was executed e.g. the django view name

    NOTE: `client.execute` would normally handle substitution, but
    because we want to strip the comments to make it easier to copy
    and past queries from the `system.query_log` easily with metabase
    (metabase doesn't show new lines, so with comments, you can't get
    a working query without exporting to csv or similar), we need to
    do it manually.

    We only want to try to substitue for SELECT queries, which
    clickhouse_driver at this moment in time decides based on the
    below predicate.
    """
    prepared_args: Any = QueryArgs
    if isinstance(args, (list, tuple, types.GeneratorType)):
        # If we get one of these it means we have an insert, let the clickhouse
        # client handle substitution here.
        rendered_sql = query
        prepared_args = args
    elif not args:
        # If `args` is not truthy then make prepared_args `None`, which the
        # clickhouse client uses to signal no substitution is desired. Expected
        # args balue are `None` or `{}` for instance
        rendered_sql = query
        prepared_args = None
    else:
        # Else perform the substitution so we can perform operations on the raw
        # non-templated SQL
        rendered_sql = client.substitute_params(query, args)
        prepared_args = None

    formatted_sql = sqlparse.format(rendered_sql, strip_comments=True)
    annotated_sql, tags = _annotate_tagged_query(formatted_sql, args)

    if app_settings.SHELL_PLUS_PRINT_SQL:
        print()
        print(format_sql(formatted_sql))

    return annotated_sql, prepared_args, tags


def _deserialize(result_bytes: bytes) -> List[Tuple]:
    results = []
    for x in json.loads(result_bytes):
        results.append(tuple(x))
    return results


def _serialize(result: Any) -> bytes:
    return json.dumps(result).encode("utf-8")


def _query_hash(query: str, team_id: int, args: Any) -> str:
    """
    Takes a query and returns a hex encoded hash of the query and args
    """
    if args:
        key = hashlib.md5((str(team_id) + query + json.dumps(args)).encode("utf-8")).hexdigest()
    else:
        key = hashlib.md5((str(team_id) + query).encode("utf-8")).hexdigest()
    return key


def _key_hash(query: str, args: Any) -> bytes:
    if args:
        key = hashlib.md5(query.encode("utf-8") + json.dumps(args).encode("utf-8")).digest()
    else:
        key = hashlib.md5(query.encode("utf-8")).digest()
    return key


def _annotate_tagged_query(query, args):
    """
    Adds in a /* */ so we can look in clickhouses `system.query_log`
    to easily marry up to the generating code.
    """
    tags = {"kind": (_request_information or {}).get("kind"), "id": (_request_information or {}).get("id")}
    if isinstance(args, dict) and "team_id" in args:
        tags["team_id"] = args["team_id"]
    # Annotate the query with information on the request/task
    if _request_information is not None:
        user_id = f" user_id:{_request_information['user_id']}" if _request_information.get("user_id") else ""
        query = f"/*{user_id} {_request_information['kind']}:{_request_information['id'].replace('/', '_')} */ {query}"

    return query, tags


def _notify_of_slow_query_failure(tags: Dict[str, Any]):
    tags["failed"] = True
    tags["reason"] = "timeout"
    incr("clickhouse_sync_execution_failure", tags=tags)


def format_sql(rendered_sql, colorize=True):
    formatted_sql = sqlparse.format(rendered_sql, reindent_aligned=True)
    if colorize:
        try:
            import pygments.formatters
            import pygments.lexers

            return pygments.highlight(
                formatted_sql, pygments.lexers.get_lexer_by_name("sql"), pygments.formatters.TerminalFormatter()
            )
        except:
            pass

    return formatted_sql
