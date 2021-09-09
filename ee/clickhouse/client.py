import asyncio
import hashlib
import json
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

import sqlparse
from aioch import Client
from asgiref.sync import async_to_sync
from clickhouse_driver import Client as SyncClient
from clickhouse_pool import ChPool
from django.conf import settings as app_settings
from django.core.cache import cache
from django.utils.timezone import now
from sentry_sdk.api import capture_exception

from ee.clickhouse.errors import wrap_query_error
from ee.clickhouse.timer import get_timer_thread
from posthog import redis
from posthog.constants import AnalyticsDBMS
from posthog.internal_metrics import incr, timing
from posthog.settings import (
    CLICKHOUSE_ASYNC,
    CLICKHOUSE_CA,
    CLICKHOUSE_CONN_POOL_MAX,
    CLICKHOUSE_CONN_POOL_MIN,
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_SECURE,
    CLICKHOUSE_USER,
    CLICKHOUSE_VERIFY,
    PRIMARY_DB,
    TEST,
)
from posthog.utils import get_safe_cache

CACHE_TTL = 60  # seconds
SLOW_QUERY_THRESHOLD_MS = 15000
QUERY_TIMEOUT_THREAD = get_timer_thread("ee.clickhouse.client", SLOW_QUERY_THRESHOLD_MS)

_request_information: Optional[Dict] = None


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
        **overrides,
    }

    return ChPool(**kwargs)


if PRIMARY_DB != AnalyticsDBMS.CLICKHOUSE:
    ch_client = None  # type: Client

    def async_execute(query, args=None, settings=None, with_column_types=False):
        return

    def sync_execute(query, args=None, settings=None, with_column_types=False):
        return

    def cache_sync_execute(query, args=None, redis_client=None, ttl=None, settings=None, with_column_types=False):
        return


else:
    if not TEST and CLICKHOUSE_ASYNC:
        ch_client = Client(
            host=CLICKHOUSE_HOST,
            database=CLICKHOUSE_DATABASE,
            secure=CLICKHOUSE_SECURE,
            user=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            ca_certs=CLICKHOUSE_CA,
            verify=CLICKHOUSE_VERIFY,
        )

        ch_pool = make_ch_pool()

        @async_to_sync
        async def async_execute(query, args=None, settings=None, with_column_types=False):
            loop = asyncio.get_event_loop()
            task = loop.create_task(
                ch_client.execute(query, args, settings=settings, with_column_types=with_column_types)
            )
            return task

    else:
        # if this is a test use the sync client
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

    def sync_execute(query, args=None, settings=None, with_column_types=False):
        with ch_pool.get_client() as client:
            start_time = perf_counter()
            tags = {}
            if app_settings.SHELL_PLUS_PRINT_SQL:
                print()
                print(format_sql(query, args))

            sql, tags = _annotate_tagged_query(query, args)
            timeout_task = QUERY_TIMEOUT_THREAD.schedule(_notify_of_slow_query_failure, tags)

            try:
                result = client.execute(sql, args, settings=settings, with_column_types=with_column_types)
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
                if _request_information is not None and _request_information.get("save", False):
                    save_query(query, args, execution_time)
        return result


def _deserialize(result_bytes: bytes) -> List[Tuple]:
    results = []
    for x in json.loads(result_bytes):
        results.append(tuple(x))
    return results


def _serialize(result: Any) -> bytes:
    return json.dumps(result).encode("utf-8")


def _key_hash(query: str, args: Any) -> bytes:
    key = hashlib.md5(query.encode("utf-8") + json.dumps(args).encode("utf-8")).digest()
    return key


def _annotate_tagged_query(query, args):
    tags = {"kind": (_request_information or {}).get("kind"), "id": (_request_information or {}).get("id")}
    if isinstance(args, dict) and "team_id" in args:
        tags["team_id"] = args["team_id"]
    # Annotate the query with information on the request/task
    if _request_information is not None:
        query = f"/* {_request_information['kind']}:{_request_information['id'].replace('/', '_')} */ {query}"

    return query, tags


def _notify_of_slow_query_failure(tags: Dict[str, Any]):
    tags["failed"] = True
    tags["reason"] = "timeout"
    incr("clickhouse_sync_execution_failure", tags=tags)


def format_sql(sql, params, colorize=True):
    substitute_params = (
        ch_client.substitute_params if isinstance(ch_client, SyncClient) else ch_client._client.substitute_params
    )
    sql = substitute_params(sql, params or {})
    sql = sqlparse.format(sql, reindent_aligned=True)
    if colorize:
        try:
            import pygments.formatters
            import pygments.lexers

            sql = pygments.highlight(
                sql, pygments.lexers.get_lexer_by_name("sql"), pygments.formatters.TerminalFormatter()
            )
        except:
            pass

    return sql


def save_query(sql: str, params: Dict, execution_time: float) -> None:
    """
    Save query for debugging purposes
    """
    if _request_information is None:
        return

    try:
        key = "save_query_{}".format(_request_information["user_id"])
        queries = json.loads(get_safe_cache(key) or "[]")

        queries.insert(
            0,
            {
                "timestamp": now().isoformat(),
                "query": format_sql(sql, params, colorize=False),
                "execution_time": execution_time,
            },
        )
        cache.set(key, json.dumps(queries), timeout=120)
    except Exception as e:
        capture_exception(e)
