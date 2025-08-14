from unittest.mock import MagicMock, patch

import dagster
import pytest
from dagster import OpExecutionContext
from dagster_aws.s3.resources import S3Resource

from dags.max_ai.snapshot_project_data import (
    snapshot_postgres_model,
    snapshot_postgres_project_data,
)
from ee.hogai.eval.schema import PostgresProjectDataSnapshot, TeamSnapshot


@pytest.fixture
def mock_context():
    context = MagicMock(spec=OpExecutionContext)
    context.log = MagicMock()
    return context


@pytest.fixture
def mock_s3():
    mock = MagicMock(spec=S3Resource)
    mock.get_resource_definition = S3Resource().get_resource_definition
    return mock


@patch("dags.max_ai.snapshot_project_data.compose_postgres_dump_path")
@patch("dags.max_ai.snapshot_project_data.check_dump_exists")
def test_snapshot_postgres_model_skips_when_file_exists(
    mock_check_dump_exists, mock_compose_path, mock_context, mock_s3
):
    """Test that snapshot_postgres_model skips dumping when file already exists."""
    # Setup
    file_key = "test/path/teams_abc123.avro"
    mock_compose_path.return_value = file_key
    mock_check_dump_exists.return_value = True

    project_id = 123
    file_name = "teams"
    code_version = "v1"

    # Execute
    result = snapshot_postgres_model(
        context=mock_context,
        model_type=TeamSnapshot,
        file_name=file_name,
        s3=mock_s3,
        project_id=project_id,
        code_version=code_version,
    )

    # Verify
    assert result == file_key
    mock_compose_path.assert_called_once_with(project_id, file_name, code_version)
    mock_check_dump_exists.assert_called_once_with(mock_s3, file_key)
    mock_context.log.info.assert_called_once_with(f"Skipping {file_key} because it already exists")


@patch("dags.max_ai.snapshot_project_data.compose_postgres_dump_path")
@patch("dags.max_ai.snapshot_project_data.check_dump_exists")
@patch("dags.max_ai.snapshot_project_data.dump_model")
def test_snapshot_postgres_model_dumps_when_file_not_exists(
    mock_dump_model, mock_check_dump_exists, mock_compose_path, mock_context, mock_s3
):
    """Test that snapshot_postgres_model dumps data when file doesn't exist."""
    # Setup
    file_key = "test/path/teams_abc123.avro"
    mock_compose_path.return_value = file_key
    mock_check_dump_exists.return_value = False

    # Mock the context manager and dump function
    mock_dump_context = MagicMock()
    mock_dump_function = MagicMock()
    mock_dump_context.__enter__ = MagicMock(return_value=mock_dump_function)
    mock_dump_context.__exit__ = MagicMock(return_value=None)
    mock_dump_model.return_value = mock_dump_context

    # Mock the serialize_for_project method
    mock_serialized_data = [{"id": 1, "name": "test"}]
    with patch.object(TeamSnapshot, "serialize_for_project", return_value=mock_serialized_data):
        project_id = 123
        file_name = "teams"
        code_version = "v1"

        # Execute
        result = snapshot_postgres_model(
            context=mock_context,
            model_type=TeamSnapshot,
            file_name=file_name,
            s3=mock_s3,
            project_id=project_id,
            code_version=code_version,
        )

    # Verify
    assert result == file_key
    mock_compose_path.assert_called_once_with(project_id, file_name, code_version)
    mock_check_dump_exists.assert_called_once_with(mock_s3, file_key)
    mock_context.log.info.assert_called_with(f"Dumping {file_key}")
    mock_dump_model.assert_called_once_with(s3=mock_s3, schema=TeamSnapshot, file_key=file_key)
    mock_dump_function.assert_called_once_with(mock_serialized_data)


@patch("dags.max_ai.snapshot_project_data.snapshot_postgres_model")
def test_snapshot_postgres_project_data_exports_all_models(mock_snapshot_postgres_model, mock_s3):
    """Test that snapshot_postgres_project_data exports all expected models."""
    # Setup
    project_id = 456
    mock_snapshot_postgres_model.side_effect = [
        "path/to/project.avro",
        "path/to/property_definitions.avro",
        "path/to/group_type_mappings.avro",
        "path/to/data_warehouse_tables.avro",
    ]

    # Create context using Dagster's build_op_context
    context = dagster.build_op_context()

    # Execute
    result = snapshot_postgres_project_data(context, project_id, mock_s3)

    # Verify all expected models are in the result
    assert isinstance(result, PostgresProjectDataSnapshot)
    assert result.project == "path/to/project.avro"
    assert result.property_definitions == "path/to/property_definitions.avro"
    assert result.group_type_mappings == "path/to/group_type_mappings.avro"
    assert result.data_warehouse_tables == "path/to/data_warehouse_tables.avro"

    # Verify snapshot_postgres_model was called for each model type
    assert mock_snapshot_postgres_model.call_count == 4
