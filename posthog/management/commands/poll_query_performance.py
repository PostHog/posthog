import time

from structlog import get_logger
from django.core.management.base import BaseCommand
import math
import re
from posthog.utils import UUID_REGEX
from posthog import redis
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.execute_async import QueryStatusManager

logger = get_logger(__name__)

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


class Command(BaseCommand):
    help = "Start Poll Query Performance Worker"

    def handle(self, *args, **options):
        while True:
            s = time.time()

            try:
                redis_client = redis.get_client()

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
                    team_id = keys[0].decode("utf-8").split(":")[2]
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

            e = time.time()
            elapsed = e - s
            if elapsed < 1:
                time.sleep(1 - elapsed)
