import uuid
from typing import Dict, Generator, List

from dateutil.relativedelta import relativedelta
from django.utils import timezone
import sqlparse

from ee.clickhouse.client import sync_execute

SLOW_THRESHOLD_MS = 10000
SLOW_AFTER = relativedelta(hours=6)

SystemStatusRow = Dict


def system_status() -> Generator[SystemStatusRow, None, None]:
    alive = is_alive()
    yield {"key": "clickhouse_alive", "metric": "Clickhouse database alive", "value": alive}

    if not alive:
        return

    disk_status = sync_execute(
        "SELECT formatReadableSize(total_space), formatReadableSize(free_space) FROM system.disks"
    )

    for index, (total_space, free_space) in enumerate(disk_status):
        metric = "Clickhouse disk" if len(disk_status) == 1 else f"Clickhouse disk {index}"
        yield {"key": f"clickhouse_disk_{index}_free_space", "metric": f"{metric} free space", "value": free_space}
        yield {"key": f"clickhouse_disk_{index}_total_space", "metric": f"{metric} total space", "value": total_space}

    table_sizes = sync_execute(
        """
        SELECT
            table,
            formatReadableSize(sum(bytes)) AS size,
            sum(rows) AS rows
        FROM system.parts
        WHERE active
        GROUP BY table
        ORDER BY rows DESC
    """
    )

    yield {
        "key": "clickhouse_table_sizes",
        "metric": "Clickhouse table sizes",
        "value": "",
        "subrows": {"columns": ["Table", "Size", "Rows"], "rows": table_sizes},
    }

    system_metrics = sync_execute("SELECT * FROM system.asynchronous_metrics")
    system_metrics += sync_execute("SELECT * FROM system.metrics")

    yield {
        "key": "clickhouse_system_metrics",
        "metric": "Clickhouse system metrics",
        "value": "",
        "subrows": {"columns": ["Metric", "Value", "Description"], "rows": list(sorted(system_metrics))},
    }


def is_alive() -> bool:
    try:
        sync_execute("SELECT 1")
        return True
    except:
        return False


def get_clickhouse_running_queries() -> List[Dict]:
    return query_with_columns(
        "SELECT elapsed as duration, query, * FROM system.processes ORDER BY duration DESC",
        columns_to_remove=["address", "initial_address", "elapsed"],
    )


def get_clickhouse_slow_log() -> List[Dict]:
    return query_with_columns(
        f"""
            SELECT query_duration_ms as duration, query, *
            FROM system.query_log
            WHERE query_duration_ms > {SLOW_THRESHOLD_MS}
              AND event_time > %(after)s
            ORDER BY duration DESC
            LIMIT 200
        """,
        {"after": timezone.now() - SLOW_AFTER},
        columns_to_remove=[
            "address",
            "initial_address",
            "query_duration_ms",
            "event_time",
            "event_date",
            "query_start_time_microseconds",
            "thread_ids",
            "ProfileEvents.Names",
            "ProfileEvents.Values",
            "Settings.Names",
            "Settings.Values",
        ],
    )


def query_with_columns(query, args=None, columns_to_remove=[]) -> List[Dict]:
    metrics, types = sync_execute(query, args, with_column_types=True)
    type_names = [key for key, _type in types]

    rows = []
    for row in metrics:
        result = {}
        for type_name, value in zip(type_names, row):
            if isinstance(value, list):
                value = ", ".join(map(str, value))
            if type_name not in columns_to_remove:
                result[type_name] = value

        rows.append(result)

    return rows

def analyze_query(query: str):
    result = {}

    query_id = str(uuid.uuid4())

    # Run the query once
    sync_execute(f"""
        -- analyze_query:${query_id}
        {query}
    """, settings={
        "allow_introspection_functions": 1,
        "query_profiler_real_time_period_ns": 40000000,
        "query_profiler_cpu_time_period_ns": 40000000,
        "memory_profiler_step": 1048576,
        "max_untracked_memory": 1048576,
        "memory_profiler_sample_probability": 0.01,
        "use_uncompressed_cache": 0
    })

    # :TODO: Stable host?

    return {
        "query": sqlparse.format(query, reindent_aligned=True),
        "timing": get_query_timing_info(query_id),
        "flamegraphs": get_flamegraphs(query_id),
    }


def get_query_timing_info(query_id: str) -> Dict:
    results = sync_execute(f"""
        SELECT
            event_time,
            query_duration_ms,
            read_rows,
            formatReadableSize(read_bytes) as read_size,
            result_rows,
            formatReadableSize(result_bytes) as result_size,
            formatReadableSize(memory_usage) as memory_usage
        FROM system.query_log
        WHERE query_id=%(query_id)s AND type = 'QueryFinish'
        LIMIT 1
    """, { query_id: query_id })

    return dict(zip(["event_time", "query_duration_ms", "read_rows", "read_size", "result_rows", "result_size", "memory_usage"], results[0]))

# def get_flamegraphs(query_id: str) -> Dict:

