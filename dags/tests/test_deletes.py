import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from dagster import build_asset_context
import uuid

from ..deletes import (
    pending_person_deletions,
    create_pending_deletes_table,
    DeleteConfig,
)
from posthog.models.async_deletion import AsyncDeletion


@pytest.fixture
def mock_async_deletion():
    return MagicMock(spec=AsyncDeletion)


@pytest.fixture
def test_config():
    return DeleteConfig(team_id=1, file_path="/tmp/test_pending_deletions.parquet")


def test_pending_person_deletions_with_team_id(mock_async_deletion):
    # Setup test data
    mock_deletions = [
        {"team_id": 1, "key": str(uuid.uuid4()), "created_at": "2025-01-15T00:00:00Z"},
        {"team_id": 1, "key": str(uuid.uuid4()), "created_at": "2025-01-15T00:00:00Z"},
    ]

    with patch("dags.deletes.AsyncDeletion.objects") as mock_objects:
        mock_filter = MagicMock()
        mock_filter.values.return_value = mock_deletions
        mock_objects.filter.return_value = mock_filter

        context = build_asset_context()
        config = DeleteConfig(team_id=1, file_path="/tmp/test_pending_deletions.parquet")

        result = pending_person_deletions(context, config)

        assert result["total_rows"] == "2"
        assert result["file_path"] == "/tmp/test_pending_deletions.parquet"

        # Verify the parquet file was created with correct data
        df = pd.read_parquet("/tmp/test_pending_deletions.parquet")
        assert len(df) == 2
        assert list(df.columns) == ["team_id", "key", "created_at"]


def test_pending_person_deletions_without_team_id(mock_async_deletion):
    # Setup test data
    mock_deletions = [
        {"team_id": 1, "key": str(uuid.uuid4()), "created_at": "2025-01-15T00:00:00Z"},
        {"team_id": 2, "key": str(uuid.uuid4()), "created_at": "2025-01-15T00:00:00Z"},
    ]

    with patch("dags.deletes.AsyncDeletion.objects") as mock_objects:
        mock_filter = MagicMock()
        mock_filter.values.return_value.iterator.return_value = mock_deletions
        mock_objects.filter.return_value = mock_filter

        context = build_asset_context()
        config = DeleteConfig(team_id=0, file_path="/tmp/test_pending_deletions.parquet")

        result = pending_person_deletions(context, config)

        assert result["total_rows"] == "2"
        assert result["file_path"] == "/tmp/test_pending_deletions.parquet"


@patch("dags.deletes.sync_execute")
def test_create_pending_deletes_table(mock_sync_execute):
    result = create_pending_deletes_table()

    assert result is True
    mock_sync_execute.assert_called_once()
    # Verify the SQL contains the expected table creation
    call_args = mock_sync_execute.call_args[0][0]
    assert "CREATE TABLE IF NOT EXISTS pending_person_deletes" in call_args
    assert "team_id Int64" in call_args
    assert "person_id UUID" in call_args


def teardown_module(module):
    # Clean up test files
    try:
        os.remove("/tmp/test_pending_deletions.parquet")
    except FileNotFoundError:
        pass
