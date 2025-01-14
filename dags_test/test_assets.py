import pytest
from unittest.mock import patch, mock_open

from dagster import build_op_context

from dags.assets import (
    get_clickhouse_version,
    print_clickhouse_version,
    ClickHouseConfig,
)


@pytest.fixture
def mock_sync_execute():
    with patch("dags.assets.sync_execute") as mock:
        mock.return_value = [["23.8.1.2992"]]
        yield mock


@pytest.fixture
def config():
    return ClickHouseConfig(result_path="/tmp/test_clickhouse_version.txt")


def test_get_clickhouse_version(mock_sync_execute, config):
    # Create a test context with our config
    context = build_op_context(resources={}, config=config)

    # Mock the file write operation
    mock_file = mock_open()
    with patch("builtins.open", mock_file):
        result = get_clickhouse_version(context)

    # Verify the SQL query was executed
    mock_sync_execute.assert_called_once_with("SELECT version()")

    # Verify the version was written to file
    mock_file().write.assert_called_once_with("23.8.1.2992")

    # Verify the result metadata
    assert result.metadata == {"version": "23.8.1.2992"}


def test_print_clickhouse_version(config):
    # Create a test context with our config
    context = build_op_context(resources={}, config=config)

    # Mock the file read operation
    mock_file = mock_open(read_data="23.8.1.2992")
    with patch("builtins.open", mock_file) as mock_open_:
        with patch("builtins.print") as mock_print:
            result = print_clickhouse_version(context)

            # Verify the file was read
            mock_open_.assert_called_once_with(config.result_path)

            # Verify the version was printed
            mock_print.assert_called_once_with("23.8.1.2992")

            # Verify the result metadata
            assert result.metadata == {"version": config.result_path}


def test_assets_integration(mock_sync_execute, config):
    """Test that both assets work together in sequence"""
    context = build_op_context(resources={}, config=config)

    # First run get_clickhouse_version
    mock_write = mock_open()
    with patch("builtins.open", mock_write):
        get_clickhouse_version(context)
        mock_write().write.assert_called_once_with("23.8.1.2992")

    # Then run print_clickhouse_version
    mock_read = mock_open(read_data="23.8.1.2992")
    with patch("builtins.open", mock_read):
        with patch("builtins.print") as mock_print:
            print_clickhouse_version(context)
            mock_print.assert_called_once_with("23.8.1.2992")
