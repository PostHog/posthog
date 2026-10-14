import re
import math
from collections.abc import Iterator
from concurrent.futures import Future
from functools import partial
from itertools import groupby
from time import perf_counter
from typing import Any, Optional

from structlog import get_logger

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.clickhouse.native_metadata import metadata_connection, submit_legacy_metadata, submit_native_metadata
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.event.new_events_schema import get_new_events_cluster_host
from posthog.settings import CLICKHOUSE_CLUSTER
from posthog.utils import UUID_REGEX

logger = get_logger(__name__)


_LEGACY_POLL_TIMEOUT_SECONDS = 3.0


def query_manager_from_initial_query_id(initial_query_id: str) -> Optional[QueryStatusManager]:
    # extract team_id and uuid from initial_query_id
    m = re.match(rf"(\d+)_({UUID_REGEX})", initial_query_id, re.I)
    if m is None:
        return None
    team_id = int(m.group(1))
    query_id = m.group(2)
    return QueryStatusManager(query_id, team_id)


def get_query_result_batches() -> Iterator[list[dict[str, Any]]]:
    from posthog.tasks.tasks import Polling  # noqa: PLC0415 - task imports this worker lazily

    started = perf_counter()
    tag_queries(product=Product.INTERNAL, feature=Feature.HEALTH_CHECK, name="poll_query_performance")
    SYSTEM_PROCESSES_SQL = r"""
        SELECT
            initial_query_id,
            read_rows,
            read_bytes,
            total_rows_approx,
            elapsed,
            ProfileEvents['OSCPUVirtualTimeMicroseconds'] as OSCPUVirtualTimeMicroseconds,
            query_id
        FROM clusterAllReplicas(%(cluster)s, system.processes)
        WHERE initial_query_id REGEXP '\d+_[0-9a-f]{8}-'
        UNION ALL SELECT
            initial_query_id,
            read_rows,
            read_bytes,
            read_rows as total_rows_approx,
            query_duration_ms / 1000 as elapsed,
            ProfileEvents['OSCPUVirtualTimeMicroseconds'] as OSCPUVirtualTimeMicroseconds,
            query_id
        FROM clusterAllReplicas(%(cluster)s, system.query_log)
        WHERE initial_query_id REGEXP '\d+_[0-9a-f]{8}-'
        AND type = 'QueryFinish'
        AND event_time > subtractSeconds(now(), 10)
        SETTINGS skip_unavailable_shards=1
        """

    try:
        native_host = get_new_events_cluster_host()
    except Exception:
        logger.exception("Failed to resolve native query progress host")
        native_host = None

    native = None
    if native_host:
        try:
            native = submit_native_metadata(
                {
                    "operation": "poll",
                    "sql": SYSTEM_PROCESSES_SQL,
                    "cluster": CLICKHOUSE_CLUSTER,
                    "connection": metadata_connection(native_host=native_host, polling=True),
                },
                polling=True,
            )
        except Exception:
            logger.exception("Failed to prepare native query progress")
    try:
        if native_host:
            legacy = submit_legacy_metadata(
                {
                    "operation": "poll",
                    "sql": SYSTEM_PROCESSES_SQL,
                    "cluster": CLICKHOUSE_CLUSTER,
                    "connection": metadata_connection(polling=True),
                },
                polling=True,
            )
            if legacy is None:
                raw_results = []
            else:
                try:
                    raw_results = legacy.result(timeout=_LEGACY_POLL_TIMEOUT_SECONDS)
                except TimeoutError:
                    legacy.add_done_callback(partial(_log_detached_poll, "legacy"))
                    raise
        else:
            raw_results = sync_execute(
                SYSTEM_PROCESSES_SQL,
                {"cluster": CLICKHOUSE_CLUSTER},
                workload=Workload.ONLINE,
                ch_user=ClickHouseUser.OPS,
            )
    except Exception:
        if not native_host:
            raise
        logger.exception("Failed to poll legacy query progress")
        raw_results = []
    # Publish healthy legacy results before waiting on the separate native cluster.
    yield _format_results(raw_results)
    if not native_host:
        return
    remaining = min(3.0, Polling.SOFT_TIME_LIMIT_SECONDS - 1 - (perf_counter() - started))
    if native is None:
        return
    try:
        yield _format_results(native.result(timeout=max(0.0, remaining)))
    except TimeoutError:
        logger.warning("Native query progress exceeded polling budget")
        native.add_done_callback(partial(_log_detached_poll, "native"))
    except Exception:
        logger.exception("Failed to poll native query progress")


def _log_detached_poll(cluster: str, future: Future[list[Any]]) -> None:
    if not future.cancelled() and (error := future.exception()) is not None:
        logger.warning("Detached query progress failed", cluster=cluster, error=str(error))


def _format_results(raw_results: list[Any]) -> list[dict[str, Any]]:
    noNaNInt = lambda num: 0 if math.isnan(num) else int(num)

    return [
        {
            "initial_query_id": result[0],
            "query_id": result[6],
            "bytes_read": noNaNInt(result[2]),
            "rows_read": noNaNInt(result[1]),
            "estimated_rows_total": noNaNInt(result[3]),
            "time_elapsed": noNaNInt(result[4]),
            "active_cpu_time": noNaNInt(result[5]),
        }
        for result in raw_results
    ]


def poll_query_performance() -> None:
    try:
        previous: dict[str, list[dict[str, Any]]] = {}
        for results in get_query_result_batches():
            key_func = lambda x: x["initial_query_id"]
            results.sort(key=key_func)
            for initial_query_id, results_group in groupby(results, key=key_func):
                manager = query_manager_from_initial_query_id(initial_query_id)
                if manager is None:
                    continue
                progress = previous.setdefault(initial_query_id, [])
                progress.extend(results_group)
                manager.update_clickhouse_query_progresses(progress.copy())

    except Exception as e:
        logger.exception("Clickhouse Status Check Failed", error=e)
