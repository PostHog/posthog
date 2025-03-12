from datetime import datetime
from unittest.mock import MagicMock

import pytest
from dags.backup_database import Backup, get_latest_backup


@pytest.mark.parametrize("table", ["", "test"])
def test_get_latest_backup(table: str):
    mock_s3 = MagicMock()
    mock_s3.get_client().list_objects_v2.return_value = {
        "CommonPrefixes": [
            {"Prefix": "posthog/2024-01-01T07:54:04Z/"},
            {"Prefix": "posthog/2024-02-01T07:54:04Z/"},
            {"Prefix": f"posthog/2024-03-01T07:54:04Z/{f'{table}/' if table else ''}"},
        ]
    }

    result = get_latest_backup(mock_s3)

    assert isinstance(result, Backup)
    assert result.database == "posthog"
    assert result.date == datetime(2024, 3, 1, 7, 54, 4)
    assert result.base_backup is None

    expected_table = table if table else None
    assert result.table == expected_table


def test_get_latest_backup_no_backups():
    mock_s3 = MagicMock()
    mock_s3.get_client().list_objects_v2.return_value = {}

    result = get_latest_backup(mock_s3)
    assert result is None
