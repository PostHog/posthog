import datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import dagster
import responses
from dagster import build_op_context

from dags.exchange_rate import (
    OPEN_EXCHANGE_RATES_API_BASE_URL,
    ExchangeRateConfig,
    daily_exchange_rates,
    daily_exchange_rates_in_clickhouse,
    daily_exchange_rates_schedule,
    fetch_exchange_rates,
    get_date_partition_from_hourly_partition,
    hourly_exchange_rates,
    hourly_exchange_rates_in_clickhouse,
    hourly_exchange_rates_schedule,
    store_exchange_rates_in_clickhouse,
)

# Sample exchange rate data for testing
SAMPLE_EXCHANGE_RATES = {
    "EUR": 0.85,
    "GBP": 0.75,
    "JPY": 110.0,
    "CAD": 1.25,
    "AUD": 1.35,
}


class TestExchangeRateUtils:
    def test_get_date_partition_from_hourly_partition(self):
        # Test converting hourly partition to daily partition
        assert get_date_partition_from_hourly_partition("2023-01-15-08:00") == "2023-01-15"
        assert get_date_partition_from_hourly_partition("2023-01-16-23:59") == "2023-01-16"
        assert get_date_partition_from_hourly_partition("2023-01-17-00:00Z") == "2023-01-17"


class TestExchangeRateAPI:
    @responses.activate
    def test_fetch_exchange_rates_success(self):
        # Mock the API response
        date_str = "2023-01-15"
        app_id = "test_app_id"
        api_url = f"{OPEN_EXCHANGE_RATES_API_BASE_URL}/historical/{date_str}.json"

        responses.add(
            responses.GET,
            api_url,
            json={"base": "USD", "rates": SAMPLE_EXCHANGE_RATES},
            status=200,
        )

        # Create a Dagster context
        context = build_op_context()

        # Call the function
        result: Any = fetch_exchange_rates(context, date_str, app_id, OPEN_EXCHANGE_RATES_API_BASE_URL)

        # Verify the result
        assert result == SAMPLE_EXCHANGE_RATES
        assert len(responses.calls) == 1
        assert f"app_id={app_id}" in responses.calls[0].request.url

    @responses.activate
    def test_fetch_exchange_rates_api_error(self):
        # Mock API error response
        date_str = "2023-01-15"
        app_id = "test_app_id"
        api_url = f"{OPEN_EXCHANGE_RATES_API_BASE_URL}/historical/{date_str}.json"

        responses.add(
            responses.GET,
            api_url,
            json={"error": "Invalid API key"},
            status=401,
        )

        # Create a Dagster context
        context = build_op_context()

        # Verify the function raises an exception
        with pytest.raises(Exception, match="Failed to fetch exchange rates"):
            fetch_exchange_rates(context, date_str, app_id, OPEN_EXCHANGE_RATES_API_BASE_URL)

    @responses.activate
    def test_fetch_exchange_rates_empty_rates(self):
        # Mock API response with empty rates
        date_str = "2023-01-15"
        app_id = "test_app_id"
        api_url = f"{OPEN_EXCHANGE_RATES_API_BASE_URL}/historical/{date_str}.json"

        responses.add(
            responses.GET,
            api_url,
            json={"base": "USD", "rates": {}},
            status=200,
        )

        # Create a Dagster context
        context = build_op_context()

        # Verify the function raises an exception
        with pytest.raises(Exception, match="No rates found"):
            fetch_exchange_rates(context, date_str, app_id, OPEN_EXCHANGE_RATES_API_BASE_URL)


class TestExchangeRateAssets:
    @responses.activate
    def test_daily_exchange_rates(self):
        # Mock the API response
        date_str = "2023-01-15"
        app_id = "test_app_id"
        api_url = f"{OPEN_EXCHANGE_RATES_API_BASE_URL}/historical/{date_str}.json"

        responses.add(
            responses.GET,
            api_url,
            json={"base": "USD", "rates": SAMPLE_EXCHANGE_RATES},
            status=200,
        )

        # Create config and context
        config = ExchangeRateConfig(app_id=app_id)
        context = dagster.build_asset_context(partition_key=date_str)

        # Call the asset
        result: Any = daily_exchange_rates(context=context, config=config)

        # Verify the result
        assert result.value == SAMPLE_EXCHANGE_RATES

    @responses.activate
    def test_hourly_exchange_rates(self):
        # Mock the API response
        date_str = "2023-01-15"
        hourly_partition = f"{date_str}-10:00"
        app_id = "test_app_id"
        api_url = f"{OPEN_EXCHANGE_RATES_API_BASE_URL}/historical/{date_str}.json"

        responses.add(
            responses.GET,
            api_url,
            json={"base": "USD", "rates": SAMPLE_EXCHANGE_RATES},
            status=200,
        )

        # Create config and context
        config = ExchangeRateConfig(app_id=app_id)
        context = dagster.build_asset_context(partition_key=hourly_partition)

        # Call the asset
        result: Any = hourly_exchange_rates(context=context, config=config)

        # Verify the result
        assert result.value == SAMPLE_EXCHANGE_RATES

    def test_daily_exchange_rates_missing_app_id(self):
        # Create context with empty app_id
        config = ExchangeRateConfig(app_id="")
        context = dagster.build_asset_context(partition_key="2023-01-15")

        # Verify the asset raises an exception
        with pytest.raises(ValueError, match="Open Exchange Rates API key"):
            daily_exchange_rates(context=context, config=config)

    def test_hourly_exchange_rates_missing_app_id(self):
        # Create context with empty app_id
        config = ExchangeRateConfig(app_id="")
        context = dagster.build_asset_context(partition_key="2023-01-15-10:00")

        # Verify the asset raises an exception
        with pytest.raises(ValueError, match="Open Exchange Rates API key"):
            hourly_exchange_rates(context=context, config=config)


class TestExchangeRateClickhouse:
    @pytest.fixture
    def mock_clickhouse_cluster(self):
        mock_cluster = mock.MagicMock()
        mock_cluster.map_all_hosts.return_value.result.return_value = {"host1": True}
        return mock_cluster

    def test_store_exchange_rates_in_clickhouse(self, mock_clickhouse_cluster):
        # Create context
        context = build_op_context()
        date_str = "2023-01-15"

        # Call the op
        rows, values = store_exchange_rates_in_clickhouse(
            context=context, date_str=date_str, exchange_rates=SAMPLE_EXCHANGE_RATES, cluster=mock_clickhouse_cluster
        )

        # Verify results
        assert len(rows) == len(SAMPLE_EXCHANGE_RATES)
        assert all(row["date"] == date_str for row in rows)
        assert all(row["currency"] in SAMPLE_EXCHANGE_RATES for row in rows)
        assert all(row["rate"] in SAMPLE_EXCHANGE_RATES.values() for row in rows)

        # Assert values generated by the op
        assert [(date_str, currency, rate) for currency, rate in SAMPLE_EXCHANGE_RATES.items()] == values

        # Verify cluster calls
        assert mock_clickhouse_cluster.map_all_hosts.call_count == 2

    def test_daily_exchange_rates_in_clickhouse(self, mock_clickhouse_cluster):
        # Create context
        context = dagster.build_asset_context(partition_key="2023-01-15")

        # Call the asset
        result = daily_exchange_rates_in_clickhouse(
            context=context, exchange_rates=SAMPLE_EXCHANGE_RATES, cluster=mock_clickhouse_cluster
        )

        # Verify result is a MaterializeResult with correct metadata
        assert isinstance(result, dagster.MaterializeResult)
        metadata: Any = result.metadata
        assert metadata["date"].value == "2023-01-15"
        assert metadata["base_currency"].value == "USD"
        assert metadata["currencies_count"].value == len(SAMPLE_EXCHANGE_RATES)
        assert metadata["min_rate"].value == min(SAMPLE_EXCHANGE_RATES.values())
        assert metadata["max_rate"].value == max(SAMPLE_EXCHANGE_RATES.values())

    def test_hourly_exchange_rates_in_clickhouse(self, mock_clickhouse_cluster):
        # Create context
        context = dagster.build_asset_context(partition_key="2023-01-15-10:00")

        # Call the asset
        result: Any = hourly_exchange_rates_in_clickhouse(
            context=context, exchange_rates=SAMPLE_EXCHANGE_RATES, cluster=mock_clickhouse_cluster
        )

        # Verify result is a MaterializeResult with correct metadata
        assert isinstance(result, dagster.MaterializeResult)
        metadata: Any = result.metadata
        assert metadata["date"].value == "2023-01-15"
        assert metadata["base_currency"].value == "USD"
        assert metadata["currencies_count"].value == len(SAMPLE_EXCHANGE_RATES)
        assert metadata["min_rate"].value == min(SAMPLE_EXCHANGE_RATES.values())
        assert metadata["max_rate"].value == max(SAMPLE_EXCHANGE_RATES.values())


class TestExchangeRateSchedules:
    @freeze_time("2023-01-15 01:30:00")
    def test_daily_exchange_rates_schedule(self):
        # Mock the scheduled execution context
        context = dagster.build_schedule_context(scheduled_execution_time=datetime.datetime(2023, 1, 15, 1, 30))

        # Call the schedule
        result: Any = daily_exchange_rates_schedule(context=context)

        # Verify result is a RunRequest with correct partition key
        assert isinstance(result, dagster.RunRequest)

        # Scheduled on the 15th, should use the previous day: 2023-01-14
        assert result.partition_key == "2023-01-14"
        assert result.run_key == "2023-01-14"

    @freeze_time("2023-01-15 10:00:00")
    def test_hourly_exchange_rates_schedule(self):
        # Mock the scheduled execution context
        context = dagster.build_schedule_context(scheduled_execution_time=datetime.datetime(2023, 1, 15, 10, 0))

        # Call the schedule
        result: Any = hourly_exchange_rates_schedule(context=context)

        # Verify result is a RunRequest with correct partition key
        assert isinstance(result, dagster.RunRequest)

        # Should be the current day and hour: 2023-01-15-10:00
        assert result.partition_key == "2023-01-15-10:00"
        assert result.run_key == "2023-01-15-10:00"
