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
from posthog.dags.backups import (
    Backup,
    BackupConfig,
    BackupStatus,
    cleanup_old_backups,
    get_latest_backups,
    get_latest_successful_backup,
    non_sharded_backup,
    prepare_run_config,
    sharded_backup,
)


@pytest.mark.parametrize(
    "path",
    [
        "invalid/path",
        "posthog/noshard/unknown-20240101075404/",
        "posthog/table/noshard/20240101075404/",
        "",
    ],
)
def test_from_s3_path_returns_none_for_invalid_paths(path: str):
    assert Backup.from_s3_path(path) is None


def test_get_latest_backups_skips_unparseable_paths():
    mock_s3 = MagicMock()
    mock_s3.get_client().list_objects_v2.return_value = {
        "CommonPrefixes": [
            {"Prefix": "posthog/test/noshard/full-20240101075404/"},
            {"Prefix": "posthog/test/noshard/garbage/"},
            {"Prefix": "posthog/test/noshard/inc-20240201075404/"},
        ]
    }

    config = BackupConfig(database="posthog", table="test", incremental=True)
    context = dagster.build_op_context()
    result = get_latest_backups(context=context, config=config, s3=mock_s3)

    assert len(result) == 2
    assert result[0].date == "20240201075404"
    assert result[1].date == "20240101075404"


def test_get_latest_backup_empty():
    mock_s3 = MagicMock()
    mock_s3.get_client().list_objects_v2.return_value = {}

    config = BackupConfig(database="posthog", table="dummy", incremental=True)
    context = dagster.build_op_context()
    result = get_latest_backups(context=context, config=config, s3=mock_s3)

    assert result == []


@pytest.mark.parametrize("table", ["", "test"])
def test_get_latest_backup(table: str):
    mock_s3 = MagicMock()
    mock_s3.get_client().list_objects_v2.return_value = {
        "CommonPrefixes": [
            {"Prefix": f"posthog/{f'{table}/' if table else ''}noshard/full-20230101075404/"},
            {"Prefix": f"posthog/{f'{table}/' if table else ''}noshard/full-20240101075404/"},
            {"Prefix": f"posthog/{f'{table}/' if table else ''}noshard/inc-20240301075404/"},
            {"Prefix": f"posthog/{f'{table}/' if table else ''}noshard/inc-20230301075404/"},
            {"Prefix": f"posthog/{f'{table}/' if table else ''}noshard/inc-20240201075404/"},
        ]
    }

    config = BackupConfig(database="posthog", table=table, incremental=True)
    context = dagster.build_op_context()
    result = get_latest_backups(context=context, config=config, s3=mock_s3)

    assert isinstance(result, list)
    assert len(result) == 5

    assert result[0].database == "posthog"
    assert result[0].date == "20240301075404"
    assert result[0].incremental is True
    assert result[0].base_backup is None

    assert result[1].database == "posthog"
    assert result[1].date == "20240201075404"
    assert result[1].incremental is True
    assert result[1].base_backup is None

    assert result[2].database == "posthog"
    assert result[2].date == "20240101075404"
    assert result[2].incremental is False
    assert result[2].base_backup is None

    assert result[3].database == "posthog"
    assert result[3].date == "20230301075404"
    assert result[3].incremental is True
    assert result[3].base_backup is None

    assert result[4].database == "posthog"
    assert result[4].date == "20230101075404"
    assert result[4].incremental is False
    assert result[4].base_backup is None

    expected_table = table if table else None
    for backup in result:
        assert backup.table == expected_table


def test_get_latest_successful_backup_returns_latest_backup():
    config = BackupConfig(database="posthog", table="test", incremental=True)
    backup1 = Backup(database="posthog", date="20240201075404", incremental=True, table="test")
    backup1.is_done = MagicMock(return_value=True)  # type: ignore
    backup1.status = MagicMock(  # type: ignore
        return_value=BackupStatus(hostname="test", status="CREATING_BACKUP", event_time_microseconds=datetime.now())
    )

    backup2 = Backup(database="posthog", date="20240101075404", incremental=False, table="test")
    backup2.is_done = MagicMock(return_value=True)  # type: ignore
    backup2.status = MagicMock(  # type: ignore
        return_value=BackupStatus(hostname="test", status="BACKUP_CREATED", event_time_microseconds=datetime.now())
    )

    def mock_map_hosts(fn, **kwargs):
        mock_result = MagicMock()
        mock_client = MagicMock()
        mock_result.result.return_value = {"host1": fn(mock_client)}
        return mock_result

    cluster = MagicMock()
    cluster.map_hosts_by_role.side_effect = mock_map_hosts

    result = get_latest_successful_backup(
        context=dagster.build_op_context(),
        config=config,
        latest_backups=[backup1, backup2],
        cluster=cluster,
    )

    assert result == backup2


def test_get_latest_successful_backup_fails():
    config = BackupConfig(database="posthog", table="test", incremental=True)
    backup1 = Backup(database="posthog", date="20240201075404", incremental=True, table="test")
    backup1.status = MagicMock(  # type: ignore
        return_value=BackupStatus(hostname="test", status="CREATING_BACKUP", event_time_microseconds=datetime.now())
    )

    def mock_map_hosts(fn, **kwargs):
        mock_result = MagicMock()
        mock_client = MagicMock()
        mock_result.result.return_value = {"host1": fn(mock_client)}
        return mock_result

    cluster = MagicMock()
    cluster.map_hosts_by_role.side_effect = mock_map_hosts

    with pytest.raises(dagster.Failure):
        get_latest_successful_backup(
            context=dagster.build_op_context(),
            config=config,
            latest_backups=[backup1],
            cluster=cluster,
        )


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
        date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d%H%M%S")
        client.execute(
            """
            BACKUP TABLE person_distinct_id_overrides
            TO S3('http://objectstorage:19000/{bucket_name}/{database}/person_distinct_id_overrides/{shard}/full-{date}')
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
            # Flush logs to ensure backup status is recorded before checking it
            cluster.any_host(create_backup_log_table).result()
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


def _make_s3_mock() -> MagicMock:
    return MagicMock()


def _make_cluster_mock(status_value: Optional[str]) -> MagicMock:
    mock_cluster = MagicMock()

    def mock_map_hosts(fn, **kwargs):
        mock_result = MagicMock()
        return_status = (
            BackupStatus(hostname="test", status=status_value, event_time_microseconds=datetime.now())
            if status_value is not None
            else None
        )
        mock_result.result.return_value = {"host1": return_status}
        return mock_result

    mock_cluster.map_hosts_by_role.side_effect = mock_map_hosts
    mock_cluster.map_hosts_in_shard_by_role.side_effect = mock_map_hosts
    return mock_cluster


@pytest.mark.parametrize(
    "status_value, expect_cleanup",
    [
        ("BACKUP_CREATED", True),
        ("BACKUP_FAILED", False),
        ("CREATING_BACKUP", False),
        (None, False),
    ],
)
def test_cleanup_skips_or_proceeds_based_on_backup_log_status(status_value: Optional[str], expect_cleanup: bool):
    config = BackupConfig(database="posthog", table="test", incremental=True)
    # Current backup is incremental, so cleanup must check backup_log for the latest full
    current_backup = Backup(database="posthog", table="test", date="20240202000000", incremental=True)
    prior_backups = [
        Backup(database="posthog", table="test", date="20240201000000", incremental=False),
        Backup(database="posthog", table="test", date="20240102000000", incremental=True),
        Backup(database="posthog", table="test", date="20240101000000", incremental=False),
    ]

    mock_s3 = _make_s3_mock()
    mock_cluster = _make_cluster_mock(status_value)

    cleanup_old_backups(
        context=dagster.build_op_context(),
        config=config,
        s3=mock_s3,
        backup=current_backup,
        all_backups=prior_backups,
        cluster=mock_cluster,
    )

    assert mock_s3.get_client().get_paginator.called == expect_cleanup


def test_cleanup_skips_when_no_s3_backups():
    # incremental backup with no prior backups in S3 → no full found → skip
    config = BackupConfig(database="posthog", table="test", incremental=True)
    current_backup = Backup(database="posthog", table="test", date="20240202000000", incremental=True)

    mock_s3 = _make_s3_mock()
    mock_cluster = MagicMock()

    cleanup_old_backups(
        context=dagster.build_op_context(),
        config=config,
        s3=mock_s3,
        backup=current_backup,
        all_backups=[],
        cluster=mock_cluster,
    )

    mock_s3.get_client().get_paginator.assert_not_called()


def test_cleanup_skips_when_no_full_backup():
    config = BackupConfig(database="posthog", table="test", incremental=True)
    current_backup = Backup(database="posthog", table="test", date="20240202000000", incremental=True)

    # Only incrementals in the prior backup list, no full backup
    prior_backups = [
        Backup(database="posthog", table="test", date="20240101000000", incremental=True),
    ]

    mock_s3 = _make_s3_mock()
    mock_cluster = MagicMock()

    cleanup_old_backups(
        context=dagster.build_op_context(),
        config=config,
        s3=mock_s3,
        backup=current_backup,
        all_backups=prior_backups,
        cluster=mock_cluster,
    )

    mock_s3.get_client().get_paginator.assert_not_called()
    mock_cluster.map_hosts_by_role.assert_not_called()


def test_cleanup_current_full_backup_does_not_check_log():
    config = BackupConfig(database="posthog", table="test", incremental=False)
    # Current backup is the full we just created; prior list has an older full
    current_backup = Backup(database="posthog", table="test", date="20240201000000", incremental=False)
    prior_backups = [
        Backup(database="posthog", table="test", date="20240101000000", incremental=False),
    ]

    mock_s3 = _make_s3_mock()
    mock_cluster = MagicMock()

    cleanup_old_backups(
        context=dagster.build_op_context(),
        config=config,
        s3=mock_s3,
        backup=current_backup,
        all_backups=prior_backups,
        cluster=mock_cluster,
    )

    # Backup log must not be consulted because we just created this full backup
    mock_cluster.map_hosts_by_role.assert_not_called()
    mock_cluster.map_hosts_in_shard_by_role.assert_not_called()
    mock_s3.get_client().get_paginator.assert_called_once_with("list_objects_v2")


def test_cleanup_deletes_correct_backups():
    config = BackupConfig(database="posthog", table="test", incremental=True)
    # Current backup is the latest incremental; prior list has two old backups and the latest full
    current_backup = Backup(database="posthog", table="test", date="20240202000000", incremental=True)
    prior_backups = [
        Backup(database="posthog", table="test", date="20240201000000", incremental=False),
        Backup(database="posthog", table="test", date="20240102000000", incremental=True),
        Backup(database="posthog", table="test", date="20240101000000", incremental=False),
    ]

    mock_s3 = _make_s3_mock()
    mock_cluster = _make_cluster_mock("BACKUP_CREATED")

    cleanup_old_backups(
        context=dagster.build_op_context(),
        config=config,
        s3=mock_s3,
        backup=current_backup,
        all_backups=prior_backups,
        cluster=mock_cluster,
    )

    paginated_prefixes = {
        call.kwargs["Prefix"] for call in mock_s3.get_client().get_paginator.return_value.paginate.call_args_list
    }
    assert paginated_prefixes == {
        f"{prior_backups[1].path}/",
        f"{prior_backups[2].path}/",
    }


def test_cleanup_nothing_to_delete():
    config = BackupConfig(database="posthog", table="test", incremental=True)
    # Current backup is incremental; prior list has only the latest full, nothing older
    current_backup = Backup(database="posthog", table="test", date="20240202000000", incremental=True)
    prior_backups = [
        Backup(database="posthog", table="test", date="20240201000000", incremental=False),
    ]

    mock_s3 = _make_s3_mock()
    mock_cluster = _make_cluster_mock("BACKUP_CREATED")

    cleanup_old_backups(
        context=dagster.build_op_context(),
        config=config,
        s3=mock_s3,
        backup=current_backup,
        all_backups=prior_backups,
        cluster=mock_cluster,
    )

    mock_s3.get_client().get_paginator.assert_not_called()


def test_cleanup_deletes_failed_recent_backups():
    config = BackupConfig(database="posthog", table="test", incremental=True)
    current_backup = Backup(database="posthog", table="test", date="20240203000000", incremental=True)
    prior_backups = [
        Backup(database="posthog", table="test", date="20240202000000", incremental=True),
        Backup(database="posthog", table="test", date="20240201000000", incremental=False),
    ]

    statuses_by_path = {
        prior_backups[0].path: "BACKUP_FAILED",
        prior_backups[1].path: "BACKUP_CREATED",
    }

    mock_s3 = _make_s3_mock()
    mock_cluster = MagicMock()

    def mock_map_hosts(fn, **kwargs):
        mock_result = MagicMock()
        status_value = statuses_by_path.get(fn.__self__.path)
        return_status = (
            BackupStatus(hostname="test", status=status_value, event_time_microseconds=datetime.now())
            if status_value is not None
            else None
        )
        mock_result.result.return_value = {"host1": return_status}
        return mock_result

    mock_cluster.map_hosts_by_role.side_effect = mock_map_hosts

    cleanup_old_backups(
        context=dagster.build_op_context(),
        config=config,
        s3=mock_s3,
        backup=current_backup,
        all_backups=prior_backups,
        cluster=mock_cluster,
    )

    paginated_prefixes = {
        call.kwargs["Prefix"] for call in mock_s3.get_client().get_paginator.return_value.paginate.call_args_list
    }
    # Only the failed incremental should be deleted; the verified full should be kept
    assert paginated_prefixes == {f"{prior_backups[0].path}/"}
