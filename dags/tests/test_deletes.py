import os
import uuid
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from dagster import build_asset_context

from ..deletes import (
    pending_person_deletions,
    create_pending_deletes_table,
    create_pending_deletes_dictionary,
    DeleteConfig,
    get_versioned_names,
)
from posthog.models.async_deletion import AsyncDeletion


@pytest.fixture
def mock_async_deletion():
    return MagicMock(spec=AsyncDeletion)


@pytest.fixture
def test_config():
    return DeleteConfig(team_id=1, file_path="/tmp/test_pending_deletions.parquet", run_id="test_run")


@pytest.fixture
def test_config_no_team():
    return DeleteConfig(file_path="/tmp/test_pending_deletions.parquet", run_id="test_run")


@pytest.fixture
def expected_names():
    return get_versioned_names("test_run")


def test_pending_person_deletions_with_team_id():
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
        config = DeleteConfig(team_id=1, file_path="/tmp/test_pending_deletions.parquet", run_id="test_run")

        result = pending_person_deletions(context, config)

        assert result["total_rows"] == "2"
        assert result["file_path"] == "/tmp/test_pending_deletions.parquet"

        # Verify the parquet file was created with correct data
        df = pd.read_parquet("/tmp/test_pending_deletions.parquet")
        assert len(df) == 2
        assert list(df.columns) == ["team_id", "key", "created_at"]


def test_pending_person_deletions_without_team_id(test_config_no_team):
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

        result = pending_person_deletions(context, test_config_no_team)

        assert result["total_rows"] == "2"
        assert result["file_path"] == "/tmp/test_pending_deletions.parquet"


@patch("dags.deletes.sync_execute")
def test_create_pending_deletes_table(mock_sync_execute, test_config, expected_names):
    result = create_pending_deletes_table(build_asset_context(), test_config)

    assert result["table_name"] == expected_names["table"]
    mock_sync_execute.assert_called_once()
    # Verify the SQL contains the expected table creation
    call_args = mock_sync_execute.call_args[0][0]
    assert f"CREATE TABLE IF NOT EXISTS {expected_names['table']}" in call_args
    assert "team_id Int64" in call_args
    assert "person_id UUID" in call_args


@patch("dags.deletes.sync_execute")
def test_create_pending_deletes_dictionary(mock_sync_execute, test_config, expected_names):
    result = create_pending_deletes_dictionary(build_asset_context(), test_config)

    assert result["dictionary_name"] == expected_names["dictionary"]
    mock_sync_execute.assert_called_once()
    # Verify the SQL contains the expected dictionary creation
    call_args = mock_sync_execute.call_args[0][0]
    assert f"CREATE DICTIONARY IF NOT EXISTS {expected_names['dictionary']}" in call_args
    assert f"TABLE {expected_names['table']}" in call_args


def teardown_module(module):
    # Clean up test files
    try:
        os.remove("/tmp/test_pending_deletions.parquet")
    except FileNotFoundError:
        pass
