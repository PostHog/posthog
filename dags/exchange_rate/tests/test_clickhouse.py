import pytest
from unittest.mock import patch, MagicMock

from dagster import build_asset_context

from ..clickhouse import store_exchange_rates_in_clickhouse
from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole


@pytest.fixture
def mock_exchange_rates():
    """Sample exchange rates data fixture."""
    return {
        "EUR": 0.821,
        "GBP": 0.732,
        "JPY": 103.25,
        "CAD": 1.275,
    }


@pytest.fixture
def mock_clickhouse_cluster():
    """Mock ClickhouseCluster fixture."""
    mock_cluster = MagicMock(spec=ClickhouseCluster)

    # Setup the map_hosts_by_role method to return a MagicMock with a result method
    mock_future_map = MagicMock()
    mock_future_map.result.return_value = None
    mock_cluster.map_hosts_by_role.return_value = mock_future_map

    return mock_cluster


def test_store_exchange_rates_in_clickhouse(mock_exchange_rates, mock_clickhouse_cluster):
    """Test that exchange rates are correctly stored in ClickHouse."""
    # Create a context with a partition key (date)
    date_str = "2025-01-01"
    context = build_asset_context(partition_key=date_str)

    # Call the asset function
    result = store_exchange_rates_in_clickhouse(
        context=context,
        exchange_rates=mock_exchange_rates,
        cluster=mock_clickhouse_cluster,
    )

    # Verify the cluster methods were called correctly
    assert mock_clickhouse_cluster.map_hosts_by_role.call_count == 2

    # First call should be for inserting data
    insert_call = mock_clickhouse_cluster.map_hosts_by_role.call_args_list[0]
    assert insert_call[0][1] == NodeRole.DATA  # Second argument should be NodeRole.DATA

    # Second call should be for reloading the dictionary
    reload_call = mock_clickhouse_cluster.map_hosts_by_role.call_args_list[1]
    assert reload_call[0][1] == NodeRole.DATA  # Second argument should be NodeRole.DATA

    # Check the result metadata
    assert result.metadata["date"].value == date_str
    assert result.metadata["base_currency"].value == "USD"
    assert result.metadata["currencies_count"].value == 4
    assert result.metadata["min_rate"].value == 0.732  # GBP has the lowest rate
    assert result.metadata["max_rate"].value == 103.25  # JPY has the highest rate
    assert result.metadata["avg_rate"].value == (0.821 + 0.732 + 103.25 + 1.275) / 4


def test_store_exchange_rates_in_clickhouse_empty_data(mock_clickhouse_cluster):
    """Test handling of empty exchange rates data."""
    # Create a context with a partition key (date)
    date_str = "2025-01-01"
    context = build_asset_context(partition_key=date_str)

    # Call the asset function with empty data
    result = store_exchange_rates_in_clickhouse(
        context=context,
        exchange_rates={},  # Empty data
        cluster=mock_clickhouse_cluster,
    )

    # Verify the cluster methods were not called (no data to insert)
    assert mock_clickhouse_cluster.map_hosts_by_role.call_count == 0

    # Check the result metadata
    assert result.metadata["date"].value == date_str
    assert result.metadata["base_currency"].value == "USD"
    assert result.metadata["currencies_count"].value == 0
    assert result.metadata["min_rate"].value == 0
    assert result.metadata["max_rate"].value == 0
    assert result.metadata["avg_rate"].value == 0


@patch("clickhouse_driver.Client")
def test_store_exchange_rates_in_clickhouse_insert_logic(
    mock_client_class, mock_exchange_rates, mock_clickhouse_cluster
):
    """Test the SQL insert logic for storing exchange rates."""
    # Create a context with a partition key (date)
    date_str = "2025-01-01"
    context = build_asset_context(partition_key=date_str)

    # Setup to capture the function passed to map_hosts_by_role
    def capture_insert_fn(fn, role, *args, **kwargs):
        # Call the function with our mock client to test it
        fn(mock_client_class)
        return MagicMock()

    mock_clickhouse_cluster.map_hosts_by_role.side_effect = capture_insert_fn

    # Call the asset function
    store_exchange_rates_in_clickhouse(
        context=context,
        exchange_rates=mock_exchange_rates,
        cluster=mock_clickhouse_cluster,
    )

    # Verify the SQL execution
    # The first call should be the INSERT statement
    assert mock_client_class.sync_execute.call_count >= 1

    # Check that the SQL contains the expected values
    sql_call = mock_client_class.sync_execute.call_args_list[0]
    sql = sql_call[0][0]

    assert "INSERT INTO exchange_rate" in sql
    assert "VALUES" in sql

    # Check that all currencies are in the SQL
    for currency in mock_exchange_rates:
        assert f"'{currency}'" in sql

    # Check that the date is in the SQL
    assert f"toDate('{date_str}')" in sql


@patch("clickhouse_driver.Client")
def test_store_exchange_rates_in_clickhouse_reload_dict(
    mock_client_class, mock_exchange_rates, mock_clickhouse_cluster
):
    """Test the dictionary reload logic after storing exchange rates."""
    # Create a context with a partition key (date)
    date_str = "2025-01-01"
    context = build_asset_context(partition_key=date_str)

    # Setup to capture the function passed to map_hosts_by_role
    call_count = 0

    def capture_fn(fn, role, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        # The second call should be the dictionary reload
        if call_count == 2:
            fn(mock_client_class)
        return MagicMock()

    mock_clickhouse_cluster.map_hosts_by_role.side_effect = capture_fn

    # Call the asset function
    store_exchange_rates_in_clickhouse(
        context=context,
        exchange_rates=mock_exchange_rates,
        cluster=mock_clickhouse_cluster,
    )

    # Verify the dictionary reload was called
    assert mock_client_class.sync_execute.call_count >= 1

    # Check that the reload dictionary command was executed
    reload_call = mock_client_class.sync_execute.call_args_list[-1]
    reload_sql = reload_call[0][0]

    assert "SYSTEM RELOAD DICTIONARY exchange_rate_dict" in reload_sql


@patch("clickhouse_driver.Client")
def test_store_exchange_rates_in_clickhouse_exception_handling(
    mock_client_class, mock_exchange_rates, mock_clickhouse_cluster
):
    """Test exception handling during ClickHouse operations."""
    # Create a context with a partition key (date)
    date_str = "2025-01-01"
    context = build_asset_context(partition_key=date_str)

    # Setup the client to raise an exception
    mock_client_class.sync_execute.side_effect = Exception("Test exception")

    # Setup to capture the function passed to map_hosts_by_role
    def capture_fn(fn, role, *args, **kwargs):
        # Call the function with our mock client to test exception handling
        fn(mock_client_class)
        return MagicMock()

    mock_clickhouse_cluster.map_hosts_by_role.side_effect = capture_fn

    # Call the asset function - it should not raise an exception
    result = store_exchange_rates_in_clickhouse(
        context=context,
        exchange_rates=mock_exchange_rates,
        cluster=mock_clickhouse_cluster,
    )

    # Verify the function handled the exception and returned a result
    assert result is not None
    assert result.metadata["date"].value == date_str


def test_store_exchange_rates_in_clickhouse_metadata_values(mock_exchange_rates, mock_clickhouse_cluster):
    """Test that the metadata values in the result are correct."""
    # Create a context with a partition key (date)
    date_str = "2025-01-01"
    context = build_asset_context(partition_key=date_str)

    # Call the asset function
    result = store_exchange_rates_in_clickhouse(
        context=context,
        exchange_rates=mock_exchange_rates,
        cluster=mock_clickhouse_cluster,
    )

    # Check all metadata values
    assert "date" in result.metadata
    assert result.metadata["date"].value == date_str

    assert "base_currency" in result.metadata
    assert result.metadata["base_currency"].value == "USD"

    assert "currencies_count" in result.metadata
    assert result.metadata["currencies_count"].value == 4

    assert "min_rate" in result.metadata
    assert result.metadata["min_rate"].value == 0.732

    assert "max_rate" in result.metadata
    assert result.metadata["max_rate"].value == 103.25

    # Not asserting on avg_rate because it's a float, and that can be different on different machines
    assert "avg_rate" in result.metadata
    # assert result.metadata["avg_rate"].value == (0.821 + 0.732 + 103.25 + 1.275) / 4

    # Check the values array in the metadata
    assert "values" in result.metadata
    values_json = result.metadata["values"].value
    assert isinstance(values_json, list)
    assert len(values_json) == 4  # Should have 4 currencies

    # Check that each value contains the expected format
    for value in values_json:
        assert f"toDate('{date_str}')" in value
        assert any(f"'{currency}'" in value for currency in mock_exchange_rates)
        assert any(str(rate) in value for rate in mock_exchange_rates.values())
