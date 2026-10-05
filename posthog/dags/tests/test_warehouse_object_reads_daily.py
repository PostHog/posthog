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
from posthog.clickhouse.warehouse_object_reads import WAREHOUSE_OBJECT_READS_DAILY_TABLE
from posthog.dags.warehouse_object_reads_daily import (
    ROLLUP_START_DATE,
    warehouse_object_reads_daily_job,
    warehouse_object_reads_daily_schedule,
)
from posthog.models import Team

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
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


def read_comment(client_query_id: str, user_id: int, **tags: Any) -> dict[str, Any]:
    return {
        "kind": "request",
        "product": "sql_editor",
        "client_query_id": client_query_id,
        "user_id": user_id,
        **tags,
    }


def read_tags(
    *, saved_query_ids: list[str], warehouse_table_ids: list[str], directly_read_ids: list[str]
) -> dict[str, list[str]]:
    return {
        "saved_query_ids": saved_query_ids,
        "warehouse_table_ids": warehouse_table_ids,
        "directly_read_ids": directly_read_ids,
    }


def refresh_comment(workflow_id: str, materialized_saved_query_id: str) -> dict[str, Any]:
    return {
        "kind": "temporal",
        "product": "warehouse",
        "feature": "data_modeling",
        "temporal": {"workflow_id": workflow_id},
        "materialized_saved_query_id": materialized_saved_query_id,
    }


def clear_archive(client: Client) -> None:
    client.execute(f"TRUNCATE TABLE {SHARDED_QUERY_LOG_ARCHIVE_TABLE}")


def run_rollup(cluster: ClickhouseCluster, day: date) -> None:
    result = warehouse_object_reads_daily_job.execute_in_process(
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
    return sorted(
        client.execute(
            f"""
            SELECT read_kind, subject_kind, subject_id, workflow_id, read_alone,
                uniqMerge(requests), uniqMerge(users), sum(read_count), sum(duration_ms_sum), sum(read_bytes_sum)
            FROM {WAREHOUSE_OBJECT_READS_DAILY_TABLE}
            WHERE team_id = %(team_id)s AND day = %(day)s AND subject_id IN %(subject_ids)s
            GROUP BY read_kind, subject_kind, subject_id, workflow_id, read_alone
            """,
            {"team_id": team_id, "day": day, "subject_ids": subject_ids},
        )
    )


@pytest.mark.django_db
def test_rollup_counts_view_and_table_reads_and_refreshes_and_replaces_its_partition_on_rerun(
    cluster: ClickhouseCluster, team: Team
) -> None:
    day = rollup_day()
    orders = DataWarehouseSavedQuery.objects.create(
        team=team, name="orders", query={"kind": "HogQLQuery", "query": "SELECT 1"}
    )
    customers = DataWarehouseSavedQuery.objects.create(
        team=team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1"}
    )
    stripe_charges = DataWarehouseTable.objects.create(
        team=team, name="stripe_charges", format="Parquet", url_pattern="https://example.com/stripe_charges"
    )
    hubspot_contacts = DataWarehouseTable.objects.create(
        team=team, name="hubspot_contacts", format="Parquet", url_pattern="https://example.com/hubspot_contacts"
    )
    refresh_workflow_id = f"materialize-view-{uuid.uuid4()}"

    view_id, nested_view_id = str(orders.id), str(customers.id)
    table_id, joined_table_id = str(stripe_charges.id), str(hubspot_contacts.id)
    from_view = read_tags(
        saved_query_ids=[view_id, nested_view_id], warehouse_table_ids=[table_id], directly_read_ids=[view_id]
    )
    from_view_joined_to_table = read_tags(
        saved_query_ids=[view_id, nested_view_id],
        warehouse_table_ids=[table_id, joined_table_id],
        directly_read_ids=[view_id, joined_table_id],
    )
    from_table = read_tags(saved_query_ids=[], warehouse_table_ids=[table_id], directly_read_ids=[table_id])
    untagged_view_read = {"saved_query_ids": [view_id]}
    rows = [
        archive_row(team, day, log_comment=read_comment("shared", 7, **from_view), duration_ms=100),
        archive_row(team, day, log_comment=read_comment("shared", 7, **from_view), duration_ms=300),
        archive_row(team, day, log_comment=read_comment("joined", 8, **from_view_joined_to_table), duration_ms=50),
        archive_row(team, day, log_comment=read_comment("table", 9, **from_table), duration_ms=20),
        archive_row(team, day, log_comment=read_comment("untagged", 7, **untagged_view_read), duration_ms=10),
        archive_row(team, day, log_comment=read_comment("staff", 9, is_impersonated=True, **from_view)),
        archive_row(team, day, log_comment=read_comment("leaf", 7, **from_view), is_initial_query=False),
        archive_row(
            team,
            day,
            log_comment=refresh_comment(refresh_workflow_id, nested_view_id),
            duration_ms=2000,
            read_bytes=50000,
        ),
    ]
    cluster.any_host(partial(insert_archive_rows, rows)).result()

    expected = sorted(
        [
            ("read", "saved_query", view_id, "", True, 1, 1, 2, 400, 2000),
            ("read", "saved_query", view_id, "", False, 2, 2, 2, 60, 2000),
            ("read", "saved_query", nested_view_id, "", False, 2, 2, 3, 450, 3000),
            ("read", "table", table_id, "", False, 2, 2, 3, 450, 3000),
            ("read", "table", table_id, "", True, 1, 1, 1, 20, 1000),
            ("read", "table", joined_table_id, "", False, 1, 1, 1, 50, 1000),
            ("refresh", "saved_query", nested_view_id, refresh_workflow_id, False, 1, 1, 1, 2000, 50000),
        ]
    )
    subject_ids = [view_id, nested_view_id, table_id, joined_table_id]
    for _ in range(2):
        run_rollup(cluster, day)
        assert cluster.any_host(partial(read_rollup, team.pk, day, subject_ids)).result() == expected

    cluster.any_host(clear_archive).result()
    run_rollup(cluster, day)
    assert cluster.any_host(partial(read_rollup, team.pk, day, subject_ids)).result() == []


@pytest.mark.django_db
def test_rollup_of_a_day_without_archive_rows_succeeds(cluster: ClickhouseCluster) -> None:
    result = warehouse_object_reads_daily_job.execute_in_process(
        partition_key=ROLLUP_START_DATE, resources={"cluster": cluster}
    )

    assert result.success


def test_schedule_runs_after_the_archive_day_closes() -> None:
    assert isinstance(warehouse_object_reads_daily_schedule, dagster.ScheduleDefinition)
    assert warehouse_object_reads_daily_schedule.cron_schedule == "0 7 * * *"


@pytest.mark.django_db
def test_rollup_fails_before_touching_staging_while_another_run_executes(cluster: ClickhouseCluster) -> None:
    instance = dagster.DagsterInstance.ephemeral()
    other_run = instance.create_run_for_job(
        job_def=warehouse_object_reads_daily_job, status=dagster.DagsterRunStatus.STARTED
    )

    with patch("posthog.dags.warehouse_object_reads_daily.recreate_staging_table") as recreate_staging_table:
        result = warehouse_object_reads_daily_job.execute_in_process(
            partition_key=ROLLUP_START_DATE, resources={"cluster": cluster}, instance=instance, raise_on_error=False
        )

    assert not result.success
    assert other_run.run_id in str(result.all_events)
    recreate_staging_table.assert_not_called()
