from unittest.mock import MagicMock
from dagster import build_op_context
from dags.backup_database import get_latest_backup, BackupDetails


def test_get_latest_backup():
    # Mock S3 client and response
    mock_s3 = MagicMock()
    mock_s3.get_client().list_objects_v2.return_value = {
        "CommonPrefixes": [
            {"Prefix": "posthog/2024-01-01/"},
            {"Prefix": "posthog/2024-02-01/"},
            {"Prefix": "posthog/2024-03-01/"},
        ]
    }

    # Execute the op
    result = get_latest_backup(build_op_context(), MagicMock(), mock_s3)

    # Verify we got the latest backup
    assert isinstance(result, BackupDetails)
    assert result.path == "posthog/2024-03-01/"
    assert result.incremental is False
    assert result.base_backup is None


def test_get_latest_backup_no_backups():
    mock_s3 = MagicMock()
    mock_s3.get_client().list_objects_v2.return_value = {}

    result = get_latest_backup(build_op_context(), MagicMock(), mock_s3)
    assert result is None
