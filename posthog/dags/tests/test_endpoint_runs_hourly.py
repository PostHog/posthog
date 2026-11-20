import re
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from typing import Any

import pytest
import time_machine
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

import dagster
from clickhouse_driver import Client
from parameterized import parameterized

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.endpoint_runs import ENDPOINT_RUNS_HOURLY_TABLE
from posthog.dags.endpoint_runs_hourly import (
    ROLLUP_START_DATE,
    endpoint_runs_hourly_job,
    insert_rollup_into_staging,
    query_log_source as endpoint_query_log_source,
    refuse_a_day_past_query_log_retention,
)
from posthog.dags.warehouse_object_reads_daily import query_log_source as warehouse_reads_query_log_source
from posthog.models import Team

ROLLUP_MODULE = "posthog.dags.endpoint_runs_hourly"
QUERY_LOG_TABLE = "test_endpoint_runs_query_log"


@pytest.fixture(autouse=True)
def rollup_on_the_local_data_node() -> Iterator[None]:
    with patch(f"{ROLLUP_MODULE}.ROLLUP_NODE_ROLE", NodeRole.DATA):
        yield


@pytest.fixture
def query_log(cluster: ClickhouseCluster) -> Iterator[None]:
    cluster.any_host(
        lambda client: client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {QUERY_LOG_TABLE} (
                event_date Date,
                event_time DateTime,
                is_initial_query UInt8,
                type Enum8('QueryStart' = 1, 'QueryFinish' = 2, 'ExceptionBeforeStart' = 3, 'ExceptionWhileProcessing' = 4),
                query_duration_ms UInt64,
                read_bytes UInt64,
                ProfileEvents Map(String, UInt64),
                log_comment String
            ) ENGINE = MergeTree ORDER BY (event_date, event_time)
            """
        )
    ).result()
    with patch(f"{ROLLUP_MODULE}.query_log_source", return_value=QUERY_LOG_TABLE):
        yield
    cluster.any_host(lambda client: client.execute(f"DROP TABLE IF EXISTS {QUERY_LOG_TABLE}")).result()


@pytest.fixture
def endpoint_logs(cluster: ClickhouseCluster) -> Iterator[None]:
    # A merge of log_entries would collapse a redelivered line before the rollup can count it twice.
    cluster.any_host(lambda client: client.execute("SYSTEM STOP MERGES log_entries")).result()
    yield
    cluster.any_host(clear_endpoint_logs).result()
    cluster.any_host(lambda client: client.execute("SYSTEM START MERGES log_entries")).result()


def rollup_day() -> date:
    return max(date.today() - timedelta(days=2), date.fromisoformat(ROLLUP_START_DATE))


def at(day: date, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute, second))


def run_line(execution_id: str, run_at: datetime, message: str, *, level: str = "INFO") -> dict[str, Any]:
    return {"execution_id": execution_id, "timestamp": run_at, "level": level, "message": message}


def query_row(
    team: Team,
    execution_id: str,
    finished_at: datetime,
    *,
    duration_ms: int,
    read_bytes: int,
    cpu_us: int,
    query_type: str = "QueryFinish",
    is_initial_query: bool = True,
) -> dict[str, Any]:
    return {
        "event_date": finished_at.date(),
        "event_time": finished_at,
        "is_initial_query": int(is_initial_query),
        "type": query_type,
        "query_duration_ms": duration_ms,
        "read_bytes": read_bytes,
        "ProfileEvents": {"OSCPUVirtualTimeMicroseconds": cpu_us},
        "log_comment": json.dumps({"team_id": team.pk, "product": "endpoints", "endpoint_execution_id": execution_id}),
    }


def insert_run_lines(team: Team, endpoint_id: str, lines: list[dict[str, Any]], client: Client) -> None:
    # One insert per line with its own Kafka offset, as a consumer redelivery writes it, so neither insert
    # deduplication nor the ReplacingMergeTree collapses a repeated line on write.
    for offset, line in enumerate(lines):
        client.execute(
            "INSERT INTO log_entries "
            "(team_id, log_source, log_source_id, instance_id, timestamp, level, message, _offset) VALUES",
            [
                (
                    team.pk,
                    "endpoints",
                    endpoint_id,
                    line["execution_id"],
                    line["timestamp"],
                    line["level"],
                    line["message"],
                    offset,
                )
            ],
        )


def insert_queries(rows: list[dict[str, Any]], client: Client) -> None:
    columns = list(rows[0])
    client.execute(
        f"INSERT INTO {QUERY_LOG_TABLE} ({', '.join(columns)}) VALUES", [tuple(row.values()) for row in rows]
    )


def clear_endpoint_logs(client: Client) -> None:
    client.execute("TRUNCATE TABLE log_entries")


def run_rollup(cluster: ClickhouseCluster, day: date, *, succeeds: bool = True) -> None:
    # Dagster accepts only a day that has ended. ClickHouse TTL runs on the real clock, so the day itself stays recent.
    with time_machine.travel(datetime.combine(day + timedelta(days=2), time(hour=3), tzinfo=UTC)):
        result = endpoint_runs_hourly_job.execute_in_process(
            partition_key=day.isoformat(), resources={"cluster": cluster}, raise_on_error=False
        )
    assert result.success is succeeds


def read_request_shapes(team_id: int, day: date, client: Client) -> list[tuple]:
    return client.execute(
        f"""
        SELECT toHour(hour), version, execution_type, access, refresh_mode, has_variables, has_pagination,
            sum(runs), sum(cache_hits), sum(cache_misses), sum(failed), groupBitOr(active_slots),
            formatDateTime(min(first_run_at), '%%H:%%i'), formatDateTime(max(last_run_at), '%%H:%%i')
        FROM {ENDPOINT_RUNS_HOURLY_TABLE}
        WHERE team_id = %(team_id)s AND day = %(day)s
        GROUP BY ALL
        ORDER BY ALL
        """,
        {"team_id": team_id, "day": day},
    )


def read_costs(team_id: int, day: date, client: Client) -> list[tuple]:
    return client.execute(
        f"""
        SELECT toHour(hour), sum(runs), sum(cache_hits), sum(cache_misses), sum(failed),
            sum(wait_ms_sum), sum(miss_wait_ms_sum), quantilesMerge(0.5, 0.9)(miss_wait_ms_quantiles),
            sum(ch_queries), sum(ch_duration_ms_sum), sum(ch_read_bytes_sum), sum(ch_cpu_us_sum),
            quantilesMerge(0.5, 0.9)(ch_duration_ms_quantiles), quantilesMerge(0.5, 0.9)(ch_read_bytes_quantiles)
        FROM {ENDPOINT_RUNS_HOURLY_TABLE}
        WHERE team_id = %(team_id)s AND day = %(day)s
        GROUP BY ALL
        ORDER BY ALL
        """,
        {"team_id": team_id, "day": day},
    )


REQUEST_TOKENS = "version=3 refresh=cache access=personal_api_key"


@pytest.mark.django_db
@pytest.mark.usefixtures("query_log", "endpoint_logs")
def test_rollup_joins_each_run_to_the_summed_cost_of_its_queries(cluster: ClickhouseCluster, team: Team) -> None:
    day = rollup_day()
    endpoint_id = str(uuid.uuid4())
    cache_hit, stale_cache, failed, after_midnight = (str(uuid.uuid4()) for _ in range(4))
    cluster.any_host(
        partial(
            insert_run_lines,
            team,
            endpoint_id,
            [
                run_line(
                    cache_hit,
                    at(day, 10, 0, 30),
                    f"Endpoint executed · path=inline cache=hit duration_ms=5 rows=10 {REQUEST_TOKENS}",
                ),
                run_line(
                    stale_cache,
                    at(day, 10, 20),
                    f"Endpoint executed · path=inline cache=miss duration_ms=900 rows=10 {REQUEST_TOKENS}",
                ),
                run_line(
                    failed,
                    at(day, 10, 40),
                    "Endpoint execution failed · path=inline duration_ms=38 version=3 error=hogql_query_error refresh=cache access=personal_api_key",
                    level="error",
                ),
                run_line(
                    after_midnight,
                    at(day, 0, 0, 2),
                    f"Endpoint executed · path=inline cache=miss duration_ms=120 rows=10 {REQUEST_TOKENS}",
                ),
            ],
        )
    ).result()
    cluster.any_host(
        partial(
            insert_queries,
            [
                query_row(team, stale_cache, at(day, 10, 19, 58), duration_ms=300, read_bytes=1000, cpu_us=50),
                query_row(team, stale_cache, at(day, 10, 19, 59), duration_ms=200, read_bytes=3000, cpu_us=70),
                query_row(
                    team,
                    stale_cache,
                    at(day, 10, 19, 59),
                    duration_ms=9999,
                    read_bytes=9999,
                    cpu_us=9999,
                    is_initial_query=False,
                ),
                query_row(
                    team,
                    failed,
                    at(day, 10, 39, 59),
                    duration_ms=38,
                    read_bytes=100,
                    cpu_us=5,
                    query_type="ExceptionWhileProcessing",
                ),
                query_row(
                    team,
                    after_midnight,
                    at(day - timedelta(days=1), 23, 59, 58),
                    duration_ms=100,
                    read_bytes=500,
                    cpu_us=10,
                ),
            ],
        )
    ).result()

    run_rollup(cluster, day)

    assert cluster.any_host(partial(read_costs, team.pk, day)).result() == [
        (0, 1, 0, 1, 0, 120, 120, [120.0, 120.0], 1, 100, 500, 10, [100.0, 100.0], [500.0, 500.0]),
        (10, 3, 1, 1, 1, 943, 900, [900.0, 900.0], 3, 538, 4100, 125, [269.0, 453.8], [2050.0, 3610.0]),
    ]


@pytest.mark.django_db
@pytest.mark.usefixtures("query_log", "endpoint_logs")
def test_rollup_reads_request_dimensions_from_the_run_line_and_skips_rejected_requests(
    cluster: ClickhouseCluster, team: Team
) -> None:
    day = rollup_day()
    endpoint_id = str(uuid.uuid4())
    paginated_line = (
        "Endpoint executed · path=inline cache=miss duration_ms=142 rows=1024 version=3 refresh=force "
        "access=personal_api_key variables=2 filters_override=true limit=100 offset=0"
    )
    redelivered = run_line(str(uuid.uuid4()), at(day, 14, 58), paginated_line)
    cluster.any_host(
        partial(
            insert_run_lines,
            team,
            endpoint_id,
            [
                run_line(str(uuid.uuid4()), at(day, 14, 1), paginated_line),
                redelivered,
                redelivered,
                run_line(
                    str(uuid.uuid4()),
                    at(day, 14, 30),
                    "Endpoint executed · path=materialized cache=hit duration_ms=3 rows=1024 version=2",
                ),
                run_line(
                    str(uuid.uuid4()),
                    at(day, 14, 10),
                    "Endpoint execution failed · invalid request · variable path=inline cache=hit is not defined",
                    level="ERROR",
                ),
            ],
        )
    ).result()

    run_rollup(cluster, day)

    assert cluster.any_host(partial(read_request_shapes, team.pk, day)).result() == [
        (14, 2, "materialized", "", "", False, False, 1, 1, 0, 0, 1 << 6, "14:30", "14:30"),
        (14, 3, "inline", "personal_api_key", "force", True, True, 2, 0, 2, 0, 1 << 0 | 1 << 11, "14:01", "14:58"),
    ]


@pytest.mark.django_db
@pytest.mark.usefixtures("query_log", "endpoint_logs")
def test_rollup_replaces_its_day_on_rerun_and_keeps_it_when_nothing_is_staged(
    cluster: ClickhouseCluster, team: Team
) -> None:
    day = rollup_day()
    endpoint_id = str(uuid.uuid4())
    cluster.any_host(
        partial(
            insert_run_lines,
            team,
            endpoint_id,
            [
                run_line(
                    str(uuid.uuid4()),
                    at(day, 9, 5),
                    f"Endpoint executed · path=inline cache=hit duration_ms=4 rows=1 {REQUEST_TOKENS}",
                )
            ],
        )
    ).result()
    published = [(9, 3, "inline", "personal_api_key", "cache", False, False, 1, 1, 0, 0, 1 << 1, "09:05", "09:05")]
    run_rollup(cluster, day)
    assert cluster.any_host(partial(read_request_shapes, team.pk, day)).result() == published

    def insert_twice(*args: Any) -> None:
        insert_rollup_into_staging(*args)
        insert_rollup_into_staging(*args)

    with patch(f"{ROLLUP_MODULE}.insert_rollup_into_staging", side_effect=insert_twice):
        run_rollup(cluster, day)
    assert cluster.any_host(partial(read_request_shapes, team.pk, day)).result() == published

    with patch(f"{ROLLUP_MODULE}.insert_rollup_into_staging"):
        run_rollup(cluster, day, succeeds=False)
    assert cluster.any_host(partial(read_request_shapes, team.pk, day)).result() == published

    cluster.any_host(clear_endpoint_logs).result()
    run_rollup(cluster, day)
    assert cluster.any_host(partial(read_request_shapes, team.pk, day)).result() == published


@parameterized.expand(
    [
        ("inside_the_query_log", 12, False),
        ("past_the_query_log", 13, True),
    ]
)
def test_rollup_refuses_a_day_whose_query_cost_is_gone(_name: str, days_ago: int, refused: bool) -> None:
    today = date(2026, 11, 20)
    with time_machine.travel(datetime.combine(today, time(hour=3), tzinfo=UTC), tick=False):
        try:
            refuse_a_day_past_query_log_retention(today - timedelta(days=days_ago))
        except dagster.Failure:
            assert refused
        else:
            assert not refused


@parameterized.expand(
    [
        ("endpoint_runs_skip_the_logs_cluster", endpoint_query_log_source, ["endpoints"]),
        ("warehouse_reads_keep_their_clusters", warehouse_reads_query_log_source, ["logs", "endpoints"]),
    ]
)
@override_settings(CLOUD_DEPLOYMENT="US")
def test_query_log_is_read_from_the_clusters_each_job_needs(
    _name: str, query_log_source: Any, satellites: list[str]
) -> None:
    clusters = re.findall(r"clusterAllReplicas\('([^']+)'", query_log_source())

    assert clusters == [settings.CLICKHOUSE_CLUSTER, *satellites]
