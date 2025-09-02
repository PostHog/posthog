from collections.abc import Generator
from datetime import timedelta
from os.path import abspath, dirname, join
from zoneinfo import ZoneInfo

from django.utils import timezone

import posthoganalytics
from dateutil.relativedelta import relativedelta

from posthog.api.dead_letter_queue import get_dead_letter_queue_size
from posthog.cache_utils import cache_for
from posthog.clickhouse.client import query_with_columns, sync_execute
from posthog.models.event.util import get_event_count, get_event_count_for_last_month, get_event_count_month_to_date
from posthog.session_recordings.models.system_status_queries import get_recording_status_month_to_date

SLOW_THRESHOLD_MS = 10000
SLOW_AFTER = relativedelta(hours=6)

CLICKHOUSE_FLAMEGRAPH_EXECUTABLE = abspath(join(dirname(__file__), "bin", "clickhouse-flamegraph"))
FLAMEGRAPH_PL = abspath(join(dirname(__file__), "bin", "flamegraph.pl"))

SystemStatusRow = dict


def system_status() -> Generator[SystemStatusRow, None, None]:
    alive = is_alive()
    yield {
        "key": "clickhouse_alive",
        "metric": "Clickhouse database alive",
        "value": alive,
    }

    if not alive:
        return

    yield {
        "key": "clickhouse_event_count",
        "metric": "Events in ClickHouse",
        "value": get_event_count(),
    }
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

    recordings_status = None
    try:
        recordings_status = get_recording_status_month_to_date()
    except Exception as ex:
        posthoganalytics.capture_exception(ex)

    yield {
        "key": "clickhouse_session_recordings_count_month_to_date",
        "metric": "Session recordings month to date",
        "value": recordings_status.count if recordings_status else "N/A",
    }

    yield {
        "key": "clickhouse_session_recordings_events_count_month_to_date",
        "metric": "Session recordings events month to date",
        "value": recordings_status.events if recordings_status else "N/A",
    }

    yield {
        "key": "clickhouse_session_recordings_events_size_ingested",
        "metric": "Session recordings events data ingested month to date",
        "value": recordings_status.size if recordings_status else "N/A",
    }

    disk_status = sync_execute(
        "SELECT formatReadableSize(total_space), formatReadableSize(free_space) FROM system.disks"
    )

    for index, (total_space, free_space) in enumerate(disk_status):
        metric = "Clickhouse disk" if len(disk_status) == 1 else f"Clickhouse disk {index}"
        yield {
            "key": f"clickhouse_disk_{index}_free_space",
            "metric": f"{metric} free space",
            "value": free_space,
        }
        yield {
            "key": f"clickhouse_disk_{index}_total_space",
            "metric": f"{metric} total space",
            "value": total_space,
        }

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
        "subrows": {
            "columns": ["Metric", "Value", "Description"],
            "rows": sorted(system_metrics),
        },
    }

    # This timestamp is a naive timestamp (does not include a timezone)
    # ClickHouse always stores timezone agnostic unix timestamp
    # See https://clickhouse.com/docs/en/sql-reference/data-types/datetime#usage-remarks
    last_event_ingested_timestamp = sync_execute(
        """
    SELECT max(_timestamp) FROM events
    WHERE timestamp >= now() - INTERVAL 1 HOUR
    """
    )[0][0]

    # Therefore we can confidently apply the UTC timezone
    last_event_ingested_timestamp_utc = last_event_ingested_timestamp.replace(tzinfo=ZoneInfo("UTC"))

    yield {
        "key": "last_event_ingested_timestamp",
        "metric": "Last event ingested",
        "value": last_event_ingested_timestamp_utc,
    }

    dead_letter_queue_size = get_dead_letter_queue_size()

    yield {
        "key": "dead_letter_queue_size",
        "metric": "Dead letter queue size",
        "value": dead_letter_queue_size,
    }

    (
        dead_letter_queue_events_high,
        dead_letter_queue_events_last_day,
    ) = dead_letter_queue_ratio()

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


def dead_letter_queue_ratio() -> tuple[bool, int]:
    dead_letter_queue_events_last_day = get_dead_letter_queue_size(0, timezone.now() - timedelta(days=1))

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


def get_clickhouse_running_queries() -> list[dict]:
    return query_with_columns(
        "SELECT elapsed as duration, query, * FROM system.processes ORDER BY duration DESC",
        columns_to_remove=["address", "initial_address", "elapsed"],
    )


def get_clickhouse_slow_log() -> list[dict]:
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
