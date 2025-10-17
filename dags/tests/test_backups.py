import uuid
from datetime import datetime, timedelta
from functools import partial
from typing import Optional
from uuid import UUID

import pytest
from unittest.mock import MagicMock, patch

import boto3
import dagster
from clickhouse_driver import Client
from dagster_aws.s3 import S3Resource

from posthog import settings
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.cluster import ClickhouseCluster

from dags.backups import Backup, BackupConfig, get_latest_backup, non_sharded_backup, prepare_run_config, sharded_backup


@pytest.mark.parametrize("table", ["", "test"])
def test_get_latest_backup(table: str):
    mock_s3 = MagicMock()
    mock_s3.get_client().list_objects_v2.return_value = {
        "CommonPrefixes": [
            {"Prefix": f"posthog/{f'{table}/' if table else ''}noshard/2024-01-01T07:54:04Z/"},
            {"Prefix": f"posthog/{f'{table}/' if table else ''}noshard/2024-03-01T07:54:04Z/"},
            {"Prefix": f"posthog/{f'{table}/' if table else ''}noshard/2024-02-01T07:54:04Z/"},
        ]
    }

    config = BackupConfig(database="posthog", table=table)
    result = get_latest_backup(config=config, s3=mock_s3)

    assert isinstance(result, Backup)
    assert result.database == "posthog"
    assert result.date == "2024-03-01T07:54:04Z"
    assert result.base_backup is None

    expected_table = table if table else None
    assert result.table == expected_table


def run_backup_test(
    cluster: ClickhouseCluster,
    job: dagster.JobDefinition,
    job_config: BackupConfig,
    sharded: bool = False,
):
    def create_bucket(name: str, s3_client: boto3.client) -> None:
        try:
            s3_client.create_bucket(Bucket=name)
        except s3_client.exceptions.BucketAlreadyExists:
            pass

    def insert_data(client: Client) -> None:
        client.execute(
            "INSERT INTO person_distinct_id_overrides (distinct_id, person_id, _timestamp, version) VALUES",
            [
                ("a", UUID(int=0), datetime.now(), 1),
                ("b", UUID(int=3), datetime.now(), 1),
            ],
        )

    def create_backup(client: Client, bucket_name: str) -> None:
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        client.execute(
            """
            BACKUP TABLE person_distinct_id_overrides
            TO S3('http://objectstorage:19000/{bucket_name}/{database}/person_distinct_id_overrides/{shard}/{date}')
            """.format(
                bucket_name=bucket_name,
                database=settings.CLICKHOUSE_DATABASE,
                shard="noshard" if not sharded else "1",
                date=date,
            )
        )

    def create_backup_log_table(client: Client) -> None:
        client.execute(
            "SYSTEM FLUSH LOGS",
        )

    def get_backup_status(client: Client, run_id: str) -> Optional[str]:
        client.execute("SYSTEM FLUSH LOGS")
        rows = client.execute(
            """
            SELECT status FROM system.backup_log
            WHERE query_id LIKE '{run_id}%'
            ORDER BY event_time_microseconds DESC
            LIMIT 1
            """.format(run_id=run_id),
        )

        return rows[0][0] if rows else None

    bucket_name = f"test-backups-{uuid.uuid4()}"
    run_id = uuid.uuid4()
    s3_client = boto3.client(
        "s3",
        endpoint_url="http://localhost:19000",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    )
    with (
        patch("django.conf.settings.CLICKHOUSE_BACKUPS_BUCKET", bucket_name),
        patch.object(Backup, "_bucket_base_path", return_value=f"http://objectstorage:19000/{bucket_name}"),
    ):
        # Prepare needed data before running the job
        # Insert some data and create the backup log table flushing the logs
        cluster.any_host(insert_data).result()
        cluster.any_host(create_backup_log_table).result()
        create_bucket(bucket_name, s3_client)
        if job_config.incremental:
            # Create a base backup and insert more data for the incremental backup
            cluster.any_host(partial(create_backup, bucket_name=bucket_name)).result()
            cluster.any_host(insert_data).result()

        # Execute the job
        job.execute_in_process(
            run_config=prepare_run_config(job_config),
            resources={
                "cluster": cluster,
                "s3": S3Resource(
                    endpoint_url="http://localhost:19000",
                    aws_access_key_id="object_storage_root_user",
                    aws_secret_access_key="object_storage_root_password",
                ),
            },
            run_id=str(run_id),
        )

        # Assert that the backup was created
        statuses = [
            status
            for status in cluster.map_all_hosts(partial(get_backup_status, run_id=run_id)).result().values()
            if status is not None
        ]
        assert len(statuses) > 0, "No status found for the backup"
        assert all(status == "BACKUP_CREATED" for status in statuses), "Backup statuses are not all BACKUP_CREATED"


def test_full_non_sharded_backup(cluster: ClickhouseCluster):
    config = BackupConfig(
        database=settings.CLICKHOUSE_DATABASE,
        date=datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        table="person_distinct_id_overrides",
        incremental=False,
        workload=Workload.ONLINE,
    )

    run_backup_test(
        cluster=cluster,
        job=non_sharded_backup,
        job_config=config,
        sharded=False,
    )


def test_full_sharded_backup(cluster: ClickhouseCluster):
    config = BackupConfig(
        database=settings.CLICKHOUSE_DATABASE,
        date=datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        table="person_distinct_id_overrides",
        incremental=False,
        workload=Workload.ONLINE,
    )

    run_backup_test(
        cluster=cluster,
        job=sharded_backup,
        job_config=config,
        sharded=True,
    )


def test_incremental_non_sharded_backup(cluster: ClickhouseCluster):
    config = BackupConfig(
        database=settings.CLICKHOUSE_DATABASE,
        date=datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        table="person_distinct_id_overrides",
        incremental=True,
        workload=Workload.ONLINE,
    )

    run_backup_test(
        cluster=cluster,
        job=non_sharded_backup,
        job_config=config,
        sharded=False,
    )


def test_incremental_sharded_backup(cluster: ClickhouseCluster):
    config = BackupConfig(
        database=settings.CLICKHOUSE_DATABASE,
        date=datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        table="person_distinct_id_overrides",
        incremental=True,
        workload=Workload.ONLINE,
    )

    run_backup_test(
        cluster=cluster,
        job=sharded_backup,
        job_config=config,
        sharded=True,
    )
