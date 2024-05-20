import math
import re

import structlog
from celery import shared_task

from posthog import redis
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.utils import UUID_REGEX

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, max_retries=1)
def poll_query_performance() -> None:
    redis_client = redis.get_client()

    CLICKHOUSE_SQL = """
    SELECT
        initial_query_id,
        read_rows,
        read_bytes,
        total_rows_approx,
        elapsed,
        ProfileEvents['OSCPUVirtualTimeMicroseconds'] as OSCPUVirtualTimeMicroseconds
    FROM clusterAllReplicas(posthog, system.processes)
    WHERE is_initial_query = 1
    """

    try:
        results, types = sync_execute(CLICKHOUSE_SQL, with_column_types=True)

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
            # extract uuid from initial_query_id
            m = re.search(UUID_REGEX, initial_query_id, re.I)
            if m is None:
                continue
            query_id = m.group(0)
            keys = redis_client.keys(f"{QueryStatusManager.KEY_PREFIX_ASYNC_RESULTS}:{query_id}:*")
            if len(keys) == 0:
                continue
            team_id = keys[0].split(":")[2]
            manager = QueryStatusManager(query_id, team_id)

            if len(keys) == 1:
                clickhouse_query_progress_dict = {initial_query_id: new_clickhouse_query_progress}
            else:
                clickhouse_query_progress_dict = manager._get_clickhouse_query_status()
                clickhouse_query_progress_dict[initial_query_id] = new_clickhouse_query_progress
            manager.store_clickhouse_query_status(clickhouse_query_progress_dict)

    except Exception as e:
        logger.error("Clickhouse Status Check Failed", e)
        pass
