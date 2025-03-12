from unittest.mock import MagicMock, patch

import pytest
from dags.backup_clickhouse import Backup, BackupConfig, get_latest_backup


@pytest.mark.parametrize("table", ["", "test"])
def test_get_latest_backup(table: str):
    mock_s3 = MagicMock()
    mock_s3.get_client().list_objects_v2.return_value = {
        "CommonPrefixes": [
            {"Prefix": f"posthog/{f'{table}/' if table else ''}2024-01-01T07:54:04Z/"},
            {"Prefix": f"posthog/{f'{table}/' if table else ''}2024-02-01T07:54:04Z/"},
            {"Prefix": f"posthog/{f'{table}/' if table else ''}2024-03-01T07:54:04Z/"},
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
        backup.create(client, "noshard")

        client.execute.assert_called_once_with(
            """
        BACKUP TABLE test
        TO S3('https://mock_bucket.s3.amazonaws.com/posthog/test/2024-03-01T00:00:00Z/noshard')
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
        backup.create(client, "noshard")

        client.execute.assert_called_once_with(
            """
        BACKUP DATABASE posthog
        TO S3('https://mock_bucket.s3.amazonaws.com/posthog/2024-03-01T00:00:00Z/noshard')
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
        backup.create(client, "noshard")

        client.execute.assert_called_once_with(
            """
        BACKUP DATABASE posthog
        TO S3('https://mock_bucket.s3.amazonaws.com/posthog/2024-03-01T00:00:00Z/noshard')
        SETTINGS async = 1, base_backup = S3('https://mock_bucket.s3.amazonaws.com/posthog/2024-02-01T00:00:00Z/noshard')
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
        [[1]],  # 1 backup in progress
        [[0]],  # 0 backups in progress
        [[]],  # backup not found
    ]

    assert not backup.is_done(client)
    assert backup.is_done(client)

    with pytest.raises(ValueError):
        backup.is_done(client)


def test_throw_on_error():
    client = MagicMock()
    backup = Backup(
        id="test",
        database="posthog",
        date="2024-03-01T00:00:00Z",
    )

    client.execute.side_effect = [
        [
            ("node1", "BACKUP_CREATED", ""),
            ("node2", "BACKUP_CREATED", ""),
            ("node3", "BACKUP_CREATED", ""),
        ],  # All backups created correctly, no error
        [
            ("node1", "BACKUP_CREATED", ""),
            ("node2", "BACKUP_CREATED", ""),
            ("node3", "BACKUP_FAILED", "an_error"),
        ],  # One backup failed, should raise an error
    ]

    backup.throw_on_error(client)  # all good

    with pytest.raises(ValueError):
        backup.throw_on_error(client)  # one backup failed
