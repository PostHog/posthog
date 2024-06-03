from typing import Optional

from structlog import get_logger

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.utils import UUID_REGEX
import re
import math

logger = get_logger(__name__)


def query_manager_from_initial_query_id(initial_query_id: str) -> Optional[QueryStatusManager]:
    # extract team_id and uuid from initial_query_id
    m = re.match(rf"(\d+)_({UUID_REGEX})", initial_query_id, re.I)
    if m is None:
        return None
    team_id = int(m.group(1))
    query_id = m.group(2)
    return QueryStatusManager(query_id, team_id)


def poll_query_performance() -> None:
    CLICKHOUSE_SQL = """
    SELECT
        initial_query_id,
        read_rows,
        read_bytes,
        total_rows_approx,
        elapsed,
        ProfileEvents['OSCPUVirtualTimeMicroseconds'] as OSCPUVirtualTimeMicroseconds
    FROM clusterAllReplicas(posthog, system.processes)
    WHERE is_initial_query
    """
    try:
        results = sync_execute(CLICKHOUSE_SQL)

        noNaNInt = lambda num: 0 if math.isnan(num) else int(num)

        all_query_progresses = {
            result[0]: {
                "bytes_read": noNaNInt(result[2]),
                "rows_read": noNaNInt(result[1]),
                "estimated_rows_total": noNaNInt(result[3]),
                "time_elapsed": noNaNInt(result[4]),
                "active_cpu_time": noNaNInt(result[5]),
            }
            for result in results
        }
        for initial_query_id, new_clickhouse_query_progress in all_query_progresses.items():
            manager = query_manager_from_initial_query_id(initial_query_id)
            if manager is None:
                continue

            manager.update_clickhouse_query_progress(initial_query_id, new_clickhouse_query_progress)

    except Exception as e:
        logger.error("Clickhouse Status Check Failed", error=e)
