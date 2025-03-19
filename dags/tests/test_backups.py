from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from dags.backups import Backup, BackupConfig, BackupStatus, get_latest_backup, get_most_recent_status


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


def test_get_latest_backup_no_backups():
    mock_s3 = MagicMock()
    mock_s3.get_client().list_objects_v2.return_value = {}

    config = BackupConfig(database="posthog", table="")
    result = get_latest_backup(config=config, s3=mock_s3)
    assert result is None


def test_create_table_backup():
    client = MagicMock()
    backup = Backup(
        id="test",
        database="posthog",
        table="test",
        date="2024-03-01T00:00:00Z",
    )

    with patch("django.conf.settings.CLICKHOUSE_BACKUPS_BUCKET", "mock_bucket"):
        backup.create(client)

        client.execute.assert_called_once_with(
            """
        BACKUP TABLE test
        TO S3('https://mock_bucket.s3.amazonaws.com/posthog/test/noshard/2024-03-01T00:00:00Z')
        SETTINGS async = 1
        """,
            query_id="test-noshard",
        )


def test_create_database_backup():
    client = MagicMock()
    backup = Backup(
        id="test",
        database="posthog",
        date="2024-03-01T00:00:00Z",
    )

    with patch("django.conf.settings.CLICKHOUSE_BACKUPS_BUCKET", "mock_bucket"):
        backup.create(client)

        client.execute.assert_called_once_with(
            """
        BACKUP DATABASE posthog
        TO S3('https://mock_bucket.s3.amazonaws.com/posthog/noshard/2024-03-01T00:00:00Z')
        SETTINGS async = 1
        """,
            query_id="test-noshard",
        )


def test_create_incremental_backup():
    client = MagicMock()
    backup = Backup(
        id="test",
        database="posthog",
        date="2024-03-01T00:00:00Z",
        base_backup=Backup(
            id="test",
            database="posthog",
            date="2024-02-01T00:00:00Z",
        ),
    )

    with patch("django.conf.settings.CLICKHOUSE_BACKUPS_BUCKET", "mock_bucket"):
        backup.create(client)

        client.execute.assert_called_once_with(
            """
        BACKUP DATABASE posthog
        TO S3('https://mock_bucket.s3.amazonaws.com/posthog/noshard/2024-03-01T00:00:00Z')
        SETTINGS async = 1, base_backup = S3('https://mock_bucket.s3.amazonaws.com/posthog/noshard/2024-02-01T00:00:00Z')
        """,
            query_id="test-noshard",
        )


def test_is_done():
    client = MagicMock()
    backup = Backup(
        id="test",
        database="posthog",
        date="2024-03-01T00:00:00Z",
    )

    client.execute.side_effect = [
        [[1]],  # is done
        [[0]],  # is not done
    ]

    assert backup.is_done(client)
    assert not backup.is_done(client)


def test_get_most_recent_status():
    most_recent_status = get_most_recent_status(
        [
            BackupStatus(
                status="BACKUP_CREATED",
                hostname="node1",
                event_time_microseconds=datetime(2025, 3, 18),
            ),
            BackupStatus(
                status="BACKUP_FAILED",
                hostname="node2",
                event_time_microseconds=datetime(2025, 3, 17),
            ),
        ]
    )

    assert most_recent_status.status == "BACKUP_CREATED"
    assert most_recent_status.hostname == "node1"
