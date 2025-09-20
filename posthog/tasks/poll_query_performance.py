import re
import math
from itertools import groupby
from typing import Any, Optional

from structlog import get_logger

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.settings import CLICKHOUSE_CLUSTER
from posthog.utils import UUID_REGEX

logger = get_logger(__name__)


def query_manager_from_initial_query_id(initial_query_id: str) -> Optional[QueryStatusManager]:
    # extract team_id and uuid from initial_query_id
    m = re.match(rf"(\d+)_({UUID_REGEX})", initial_query_id, re.I)
    if m is None:
        return None
    team_id = int(m.group(1))
    query_id = m.group(2)
    return QueryStatusManager(query_id, team_id)


def get_query_results() -> list[Any]:
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

    raw_results = sync_execute(
        SYSTEM_PROCESSES_SQL, {"cluster": CLICKHOUSE_CLUSTER}, workload=Workload.ONLINE, ch_user=ClickHouseUser.OPS
    )

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
        results = get_query_results()

        key_func = lambda x: x["initial_query_id"]
        results.sort(key=key_func)
        for initial_query_id, results_group in groupby(results, key=key_func):
            manager = query_manager_from_initial_query_id(initial_query_id)
            if manager is None:
                continue
            manager.update_clickhouse_query_progresses(list(results_group))

    except Exception as e:
        logger.exception("Clickhouse Status Check Failed", error=e)
