import json
import uuid
from datetime import date, datetime, time, timedelta
from functools import partial
from typing import Any

import pytest
from unittest.mock import patch

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_log_archive import SHARDED_QUERY_LOG_ARCHIVE_TABLE
from posthog.clickhouse.saved_query_reads import SAVED_QUERY_READS_DAILY_TABLE
from posthog.dags.saved_query_reads_daily import (
    ROLLUP_START_DATE,
    saved_query_reads_daily_job,
    saved_query_reads_daily_schedule,
)
from posthog.models import Team

from products.data_modeling.backend.facade.models import DataModelingJob, DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


def rollup_day() -> date:
    return date.today() - timedelta(days=2)


def archive_row(
    team: Team,
    day: date,
    *,
    log_comment: dict[str, Any],
    is_initial_query: bool = True,
    duration_ms: int = 100,
    read_bytes: int = 1000,
) -> dict[str, Any]:
    query_id = str(uuid.uuid4())
    return {
        "team_id": team.pk,
        "query_id": query_id,
        "initial_query_id": query_id,
        "is_initial_query": int(is_initial_query),
        "type": "QueryFinish",
        "event_date": day,
        "event_time": datetime.combine(day, time(hour=12)),
        "query_duration_ms": duration_ms,
        "read_bytes": read_bytes,
        "log_comment": json.dumps({"team_id": team.pk, **log_comment}),
    }


def view_read_comment(
    saved_query: DataWarehouseSavedQuery, hogql: str, client_query_id: str, user_id: int, **extra: Any
) -> dict[str, Any]:
    return {
        "kind": "request",
        "product": "sql_editor",
        "client_query_id": client_query_id,
        "user_id": user_id,
        "saved_query_ids": [str(saved_query.id)],
        "query": {"kind": "HogQLQuery", "query": hogql},
        **extra,
    }


def refresh_comment(workflow_id: str) -> dict[str, Any]:
    return {
        "kind": "temporal",
        "product": "warehouse",
        "feature": "data_modeling",
        "temporal": {"workflow_id": workflow_id},
    }


def clear_archive(client: Client) -> None:
    client.execute(f"TRUNCATE TABLE {SHARDED_QUERY_LOG_ARCHIVE_TABLE}")


def run_rollup(cluster: ClickhouseCluster, day: date) -> None:
    result = saved_query_reads_daily_job.execute_in_process(
        partition_key=day.isoformat(), resources={"cluster": cluster}
    )
    assert result.success


def insert_archive_rows(rows: list[dict[str, Any]], client: Client) -> None:
    columns = list(rows[0])
    for row in rows:
        client.execute(
            f"INSERT INTO {SHARDED_QUERY_LOG_ARCHIVE_TABLE} ({', '.join(columns)}) "
            f"SELECT {', '.join(f'%({column})s' for column in columns)}",
            row,
        )


def read_rollup(team_id: int, day: date, subject_ids: list[str], client: Client) -> list[tuple]:
    return client.execute(
        f"""
        SELECT read_kind, subject_id, workflow_id, names_only_this_subject,
            uniqMerge(requests), uniqMerge(users), sum(read_count), sum(duration_ms_sum), sum(read_bytes_sum)
        FROM {SAVED_QUERY_READS_DAILY_TABLE}
        WHERE team_id = %(team_id)s AND day = %(day)s AND subject_id IN %(subject_ids)s
        GROUP BY read_kind, subject_id, workflow_id, names_only_this_subject
        ORDER BY read_kind, names_only_this_subject
        """,
        {"team_id": team_id, "day": day, "subject_ids": subject_ids},
    )


@pytest.mark.django_db
def test_rollup_counts_view_reads_and_refreshes_and_replaces_its_partition_on_rerun(
    cluster: ClickhouseCluster, team: Team
) -> None:
    day = rollup_day()
    orders = DataWarehouseSavedQuery.objects.create(
        team=team, name="orders", query={"kind": "HogQLQuery", "query": "SELECT 1"}
    )
    customers = DataWarehouseSavedQuery.objects.create(
        team=team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1"}
    )
    DataWarehouseTable.objects.create(
        team=team, name="stripe_charges", format="Parquet", url_pattern="https://example.com/stripe_charges"
    )
    retired = DataWarehouseSavedQuery.objects.create(
        team=team, name="retired", query={"kind": "HogQLQuery", "query": "SELECT 1"}, deleted=True
    )
    refresh_workflow_id = f"materialize-view-{uuid.uuid4()}"
    retired_workflow_id = f"materialize-view-{uuid.uuid4()}"
    DataModelingJob.objects.create(team=team, saved_query=customers, workflow_id=refresh_workflow_id)
    DataModelingJob.objects.create(team=team, saved_query=retired, workflow_id=retired_workflow_id)

    view_only = "SELECT count() FROM orders"
    joined = "SELECT count() FROM orders o JOIN `stripe_charges` c ON o.id = c.order_id"
    comma_joined = "SELECT count() FROM orders o, stripe_charges c WHERE o.id = c.order_id"
    commented_join = "SELECT count() FROM orders o JOIN /* warehouse */ stripe_charges c ON o.id = c.order_id"
    rows = [
        archive_row(team, day, log_comment=view_read_comment(orders, view_only, "shared", 7), duration_ms=100),
        archive_row(team, day, log_comment=view_read_comment(orders, view_only, "shared", 7), duration_ms=300),
        archive_row(team, day, log_comment=view_read_comment(orders, joined, "joined", 8), duration_ms=50),
        archive_row(team, day, log_comment=view_read_comment(orders, comma_joined, "comma", 8), duration_ms=60),
        archive_row(team, day, log_comment=view_read_comment(orders, commented_join, "comment", 8), duration_ms=70),
        archive_row(team, day, log_comment=view_read_comment(orders, view_only, "staff", 9, is_impersonated=True)),
        archive_row(team, day, log_comment=view_read_comment(orders, view_only, "leaf", 7), is_initial_query=False),
        archive_row(team, day, log_comment=refresh_comment(refresh_workflow_id), duration_ms=2000, read_bytes=50000),
        archive_row(team, day, log_comment=refresh_comment(retired_workflow_id)),
    ]
    cluster.any_host(partial(insert_archive_rows, rows)).result()

    expected = [
        ("read", str(orders.id), "", False, 3, 1, 3, 180, 3000),
        ("read", str(orders.id), "", True, 1, 1, 2, 400, 2000),
        ("refresh", str(customers.id), refresh_workflow_id, False, 1, 1, 1, 2000, 50000),
    ]
    subject_ids = [str(orders.id), str(customers.id), str(retired.id)]
    for _ in range(2):
        run_rollup(cluster, day)
        assert cluster.any_host(partial(read_rollup, team.pk, day, subject_ids)).result() == expected

    cluster.any_host(clear_archive).result()
    run_rollup(cluster, day)
    assert cluster.any_host(partial(read_rollup, team.pk, day, subject_ids)).result() == []


@pytest.mark.django_db
def test_rollup_of_a_day_without_archive_rows_succeeds(cluster: ClickhouseCluster) -> None:
    result = saved_query_reads_daily_job.execute_in_process(
        partition_key=ROLLUP_START_DATE, resources={"cluster": cluster}
    )

    assert result.success


def test_schedule_runs_after_the_archive_day_closes() -> None:
    assert isinstance(saved_query_reads_daily_schedule, dagster.ScheduleDefinition)
    assert saved_query_reads_daily_schedule.cron_schedule == "0 7 * * *"


@pytest.mark.django_db
def test_rollup_fails_before_touching_staging_while_another_run_executes(cluster: ClickhouseCluster) -> None:
    instance = dagster.DagsterInstance.ephemeral()
    other_run = instance.create_run_for_job(
        job_def=saved_query_reads_daily_job, status=dagster.DagsterRunStatus.STARTED
    )

    with patch("posthog.dags.saved_query_reads_daily.recreate_staging_table") as recreate_staging_table:
        result = saved_query_reads_daily_job.execute_in_process(
            partition_key=ROLLUP_START_DATE, resources={"cluster": cluster}, instance=instance, raise_on_error=False
        )

    assert not result.success
    assert other_run.run_id in str(result.all_events)
    recreate_staging_table.assert_not_called()
