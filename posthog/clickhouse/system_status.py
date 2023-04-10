import glob
import subprocess
import tempfile
import uuid
from datetime import timedelta
from os.path import abspath, basename, dirname, join
from typing import Dict, Generator, List, Tuple
import pytz

import sqlparse
from clickhouse_driver import Client
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from sentry_sdk.api import capture_exception

from posthog.api.dead_letter_queue import get_dead_letter_queue_events_last_24h, get_dead_letter_queue_size
from posthog.cache_utils import cache_for
from posthog.clickhouse.client.connection import make_ch_pool
from posthog.client import query_with_columns, sync_execute
from posthog.cloud_utils import is_cloud
from posthog.models.event.util import get_event_count, get_event_count_for_last_month, get_event_count_month_to_date
from posthog.models.session_recording_event.util import (
    get_recording_count_month_to_date,
    get_recording_events_count_month_to_date,
)
from posthog.settings import CLICKHOUSE_PASSWORD, CLICKHOUSE_STABLE_HOST, CLICKHOUSE_USER

SLOW_THRESHOLD_MS = 10000
SLOW_AFTER = relativedelta(hours=6)

CLICKHOUSE_FLAMEGRAPH_EXECUTABLE = abspath(join(dirname(__file__), "bin", "clickhouse-flamegraph"))
FLAMEGRAPH_PL = abspath(join(dirname(__file__), "bin", "flamegraph.pl"))

SystemStatusRow = Dict


def system_status() -> Generator[SystemStatusRow, None, None]:
    alive = is_alive()
    yield {"key": "clickhouse_alive", "metric": "Clickhouse database alive", "value": alive}

    if not alive:
        return

    yield {"key": "clickhouse_event_count", "metric": "Events in ClickHouse", "value": get_event_count()}
    yield {
        "key": "clickhouse_event_count_last_month",
        "metric": "Events recorded last month",
        "value": get_event_count_for_last_month(),
    }
    yield {
        "key": "clickhouse_event_count_month_to_date",
        "metric": "Events recorded month to date",
        "value": get_event_count_month_to_date(),
    }

    if not is_cloud():
        # NOTE: These metrics can be quite expensive to calculate and are only really interesting to self-hosted customers
        yield {
            "key": "clickhouse_session_recordings_count_month_to_date",
            "metric": "Session recordings month to date",
            "value": get_recording_count_month_to_date(),
        }

        yield {
            "key": "clickhouse_session_recordings_events_count_month_to_date",
            "metric": "Session recordings events month to date",
            "value": get_recording_events_count_month_to_date(),
        }

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

    # This timestamp is a naive timestamp (does not include a timezone)
    # ClickHouse always stores timezone agnostic unix timestamp
    # See https://clickhouse.com/docs/en/sql-reference/data-types/datetime#usage-remarks
    last_event_ingested_timestamp = sync_execute("SELECT max(_timestamp) FROM events")[0][0]

    # Therefore we can confidently apply the UTC timezone
    last_event_ingested_timestamp_utc = last_event_ingested_timestamp.replace(tzinfo=pytz.UTC)

    yield {
        "key": "last_event_ingested_timestamp",
        "metric": "Last event ingested",
        "value": last_event_ingested_timestamp_utc,
    }

    dead_letter_queue_size = get_dead_letter_queue_size()

    yield {"key": "dead_letter_queue_size", "metric": "Dead letter queue size", "value": dead_letter_queue_size}

    dead_letter_queue_events_high, dead_letter_queue_events_last_day = dead_letter_queue_ratio()

    yield {
        "key": "dead_letter_queue_events_last_day",
        "metric": "Events sent to dead letter queue in the last 24h",
        "value": dead_letter_queue_events_last_day,
    }

    yield {
        "key": "dead_letter_queue_ratio_ok",
        "metric": "Dead letter queue ratio healthy",
        "value": not dead_letter_queue_events_high,
    }


def is_alive() -> bool:
    try:
        sync_execute("SELECT 1")
        return True
    except:
        return False


def dead_letter_queue_ratio() -> Tuple[bool, int]:
    dead_letter_queue_events_last_day = get_dead_letter_queue_events_last_24h()

    total_events_ingested_last_day = sync_execute(
        "SELECT count(*) as b from events WHERE _timestamp >= (NOW() - INTERVAL 1 DAY)"
    )[0][0]

    dead_letter_queue_ingestion_ratio = dead_letter_queue_events_last_day / max(
        dead_letter_queue_events_last_day + total_events_ingested_last_day, 1
    )

    # if the dead letter queue has above 20% of events compared to ingestion, issue an alert
    return dead_letter_queue_ingestion_ratio >= 0.2, dead_letter_queue_events_last_day


@cache_for(timedelta(minutes=5))
def dead_letter_queue_ratio_ok_cached() -> bool:
    return dead_letter_queue_ratio()[0]


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
              AND query NOT LIKE '%%system.query_log%%'
              AND query NOT LIKE '%%analyze_query:%%'
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


def analyze_query(query: str):
    random_id = str(uuid.uuid4())

    # :TRICKY: Ensure all queries run on the same host.
    ch_pool = make_ch_pool(host=CLICKHOUSE_STABLE_HOST)

    with ch_pool.get_client() as conn:
        conn.execute(
            f"""
            -- analyze_query:{random_id}
            {query}
            """,
            settings={
                "allow_introspection_functions": 1,
                "query_profiler_real_time_period_ns": 40000000,
                "query_profiler_cpu_time_period_ns": 40000000,
                "memory_profiler_step": 1048576,
                "max_untracked_memory": 1048576,
                "memory_profiler_sample_probability": 0.01,
                "use_uncompressed_cache": 0,
                "readonly": 1,
                "allow_ddl": 0,
            },
        )

        query_id, timing_info = get_query_timing_info(random_id, conn)

        return {
            "query": sqlparse.format(query, reindent_aligned=True),
            "timing": timing_info,
            "flamegraphs": get_flamegraphs(query_id),
        }


def get_query_timing_info(random_id: str, conn: Client) -> Tuple[str, Dict]:
    conn.execute("SYSTEM FLUSH LOGS")
    results = conn.execute(
        """
        SELECT
            query_id,
            event_time,
            query_duration_ms,
            read_rows,
            formatReadableSize(read_bytes) as read_size,
            result_rows,
            formatReadableSize(result_bytes) as result_size,
            formatReadableSize(memory_usage) as memory_usage
        FROM system.query_log
        WHERE query NOT LIKE '%%query_log%%'
          AND match(query, %(expr)s)
          AND type = 'QueryFinish'
        LIMIT 1
    """,
        {"expr": f"analyze_query:{random_id}"},
    )

    return (
        results[0][0],
        dict(
            zip(
                [
                    "query_id",
                    "event_time",
                    "query_duration_ms",
                    "read_rows",
                    "read_size",
                    "result_rows",
                    "result_size",
                    "memory_usage",
                ],
                results[0],
            )
        ),
    )


def get_flamegraphs(query_id: str) -> Dict:
    try:
        with tempfile.TemporaryDirectory() as tmpdirname:
            subprocess.run(
                [
                    CLICKHOUSE_FLAMEGRAPH_EXECUTABLE,
                    "--query-id",
                    query_id,
                    "--clickhouse-dsn",
                    f"http://{CLICKHOUSE_USER}:{CLICKHOUSE_PASSWORD}@{CLICKHOUSE_STABLE_HOST}:8123/",
                    "--console",
                    "--flamegraph-script",
                    FLAMEGRAPH_PL,
                    "--date-from",
                    "2021-01-01",
                    "--width",
                    "1900",
                ],
                cwd=tmpdirname,
                check=True,
            )

            flamegraphs = {}
            for file_path in glob.glob(join(tmpdirname, "*/*/global*.svg")):
                with open(file_path, "r", encoding="utf_8") as file:
                    flamegraphs[basename(file_path)] = file.read()

            return flamegraphs
    except Exception as err:
        capture_exception(err)
        return {}
