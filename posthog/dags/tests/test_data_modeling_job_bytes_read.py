import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import patch

from django.utils import timezone

from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.data_modeling_job_bytes_read import data_modeling_job_bytes_read_job
from posthog.models import Team

from products.data_modeling.backend.facade.models import DataModelingJob

MODULE = "posthog.dags.data_modeling_job_bytes_read"
QUERY_LOG_TABLE = "test_data_modeling_job_bytes_read_query_log"


@pytest.fixture
def query_log(cluster: ClickhouseCluster) -> Iterator[None]:
    cluster.any_host(
        lambda client: client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {QUERY_LOG_TABLE} (
                initial_query_start_time DateTime64(6, 'UTC'),
                is_initial_query UInt8,
                type Enum8('QueryStart' = 1, 'QueryFinish' = 2, 'ExceptionBeforeStart' = 3, 'ExceptionWhileProcessing' = 4),
                read_bytes UInt64,
                lc_feature LowCardinality(String),
                lc_temporal__activity_type LowCardinality(String),
                lc_temporal__workflow_run_id String
            ) ENGINE = MergeTree ORDER BY initial_query_start_time
            """
        )
    ).result()
    with patch(f"{MODULE}.SOURCE_TABLE", QUERY_LOG_TABLE), patch(f"{MODULE}.SOURCE_NODE_ROLE", NodeRole.DATA):
        yield
    cluster.any_host(lambda client: client.execute(f"DROP TABLE IF EXISTS {QUERY_LOG_TABLE}")).result()


def insert_query_log_rows(cluster: ClickhouseCluster, rows: list[dict[str, Any]]) -> None:
    def insert(client: Client) -> None:
        client.execute(f"INSERT INTO {QUERY_LOG_TABLE} ({', '.join(rows[0])}) VALUES", rows)

    cluster.any_host(insert).result()


def query(run_id: str, started_at: datetime, read_bytes: int, **overrides: Any) -> dict[str, Any]:
    return {
        "initial_query_start_time": started_at,
        "is_initial_query": 1,
        "type": "QueryFinish",
        "read_bytes": read_bytes,
        "lc_feature": "data_modeling",
        "lc_temporal__activity_type": "materialize_view_activity",
        "lc_temporal__workflow_run_id": run_id,
        **overrides,
    }


def create_job(team: Team, updated_at: datetime | None = None, **fields: Any) -> DataModelingJob:
    job = DataModelingJob.objects.create(
        team=team,
        workflow_run_id=str(uuid.uuid4()),
        **{"status": DataModelingJob.Status.COMPLETED, **fields},
    )
    # Jobs that changed in the last minutes are skipped because the query log may still be arriving,
    # and so are jobs that changed after the window the totals were read from.
    DataModelingJob.objects.filter(id=job.id).update(updated_at=updated_at or timezone.now() - timedelta(hours=3))
    job.refresh_from_db()
    return job


def run_id_of(job: DataModelingJob) -> str:
    assert job.workflow_run_id is not None
    return job.workflow_run_id


def run(cluster: ClickhouseCluster, partition_start: datetime) -> int:
    result = data_modeling_job_bytes_read_job.execute_in_process(
        partition_key=partition_start.strftime("%Y-%m-%d-%H:%M"), resources={"cluster": cluster}
    )
    assert result.success
    return result.output_for_node("record_clickhouse_job_bytes_read")


@pytest.mark.django_db
@pytest.mark.usefixtures("query_log")
def test_writes_bytes_read_once_onto_finished_clickhouse_jobs(cluster: ClickhouseCluster, team: Team) -> None:
    partition_start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    in_window = partition_start + timedelta(minutes=10)

    measured = create_job(team)
    failed = create_job(team, status=DataModelingJob.Status.FAILED)
    running = create_job(team, status=DataModelingJob.Status.RUNNING)
    already_measured = create_job(team, bytes_read=7)
    trino = create_job(team, engine=DataModelingJob.Engine.MANAGED_WAREHOUSE)
    finished_after_window = create_job(team, updated_at=timezone.now() - timedelta(minutes=30))
    insert_query_log_rows(
        cluster,
        [
            query(run_id_of(measured), in_window, 100),
            query(run_id_of(measured), in_window - timedelta(hours=20), 50),
            query(run_id_of(measured), in_window, 1000, is_initial_query=0),
            query(run_id_of(measured), in_window, 1000, lc_temporal__activity_type="other_activity"),
            query(run_id_of(measured), in_window, 1000, lc_feature="other_feature"),
            query(run_id_of(measured), partition_start + timedelta(hours=1), 1000),
            query(run_id_of(measured), partition_start - timedelta(hours=24), 1000),
            query(run_id_of(failed), in_window, 30, type="ExceptionWhileProcessing"),
            query(run_id_of(running), in_window, 30),
            query(run_id_of(already_measured), in_window, 30),
            query(run_id_of(trino), in_window, 30),
            query(run_id_of(finished_after_window), in_window, 30),
        ],
    )

    assert run(cluster, partition_start) == 2
    assert run(cluster, partition_start) == 0

    bytes_read = dict(
        DataModelingJob.objects.filter(team=team).values_list("workflow_run_id", "bytes_read"),
    )
    assert bytes_read == {
        measured.workflow_run_id: 150,
        failed.workflow_run_id: 30,
        running.workflow_run_id: None,
        already_measured.workflow_run_id: 7,
        trino.workflow_run_id: None,
        finished_after_window.workflow_run_id: None,
    }
