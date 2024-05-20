import math
from typing import Optional

import structlog
from celery import shared_task

from posthog.clickhouse.client import sync_execute
from posthog.models import Person


logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, max_retries=1)
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
    WHERE is_initial_query = 1
    """

    try:
        results, types = sync_execute(CLICKHOUSE_SQL, with_column_types=True)

        noNaNInt = lambda num: 0 if math.isnan(num) else int(num)

        new_clickhouse_query_progress = {
            result[0]: {
                "bytes_read": noNaNInt(result[2]),
                "rows_read": noNaNInt(result[1]),
                "estimated_rows_total": noNaNInt(result[3]),
                "time_elapsed": noNaNInt(result[4]),
                "active_cpu_time": noNaNInt(result[5]),
            }
            for result in results
        }
        for initial_query_id, new_clickhouse_query_progress in new_clickhouse_query_progress.items():


        clickhouse_query_progress_dict.update(new_clickhouse_query_progress)
        self.store_clickhouse_query_status(clickhouse_query_progress_dict)

        query_progress = {
            "bytes_read": 0,
            "rows_read": 0,
            "estimated_rows_total": 0,
            "time_elapsed": 0,
            "active_cpu_time": 0,
        }
        for single_query_progress in clickhouse_query_progress_dict.values():
            query_progress["bytes_read"] += single_query_progress["bytes_read"]
            query_progress["rows_read"] += single_query_progress["rows_read"]
            query_progress["estimated_rows_total"] += single_query_progress["estimated_rows_total"]
            query_progress["time_elapsed"] += single_query_progress["time_elapsed"]
            query_progress["active_cpu_time"] += single_query_progress["active_cpu_time"]
        query_status.query_progress = ClickhouseQueryStatus(**query_progress)

    except Exception as e:
        logger.error("Clickhouse Status Check Failed", e)
        pass
