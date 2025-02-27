import pytest
import responses

from dagster import build_asset_context

from ..exchange_rate import (
    ExchangeRateConfig,
    exchange_rates,
    API_BASE_URL,
)


@pytest.fixture
def mock_api_response():
    return {
        "disclaimer": "Usage subject to terms: https://openexchangerates.org/terms",
        "license": "https://openexchangerates.org/license",
        "timestamp": 1609459199,
        "base": "USD",
        "rates": {
            "EUR": 0.821,
            "GBP": 0.732,
            "JPY": 103.25,
            "CAD": 1.275,
        },
    }


@pytest.fixture
def mock_config():
    return ExchangeRateConfig(app_id="test_app_id", api_base_url=API_BASE_URL)


@pytest.fixture
def mock_context():
    # Create a context with a partition key for 2025-01-15
    return build_asset_context(partition_key="2025-01-15")


@responses.activate
def test_exchange_rates_success(mock_api_response, mock_config, mock_context):
    """Test successful exchange rates fetch."""
    # Setup mock response
    date_str = mock_context.partition_key
    url = f"{API_BASE_URL}/historical/{date_str}.json"
    responses.add(
        responses.GET,
        url,
        json=mock_api_response,
        status=200,
    )

    # Call the asset function
    result = exchange_rates(mock_context, mock_config)

    # Verify the result
    assert result == mock_api_response["rates"]
    assert result["EUR"] == 0.821
    assert result["GBP"] == 0.732
    assert len(result) == 4


@responses.activate
def test_exchange_rates_api_error(mock_config, mock_context):
    """Test handling of API errors."""
    # Setup mock response with error
    date_str = mock_context.partition_key
    url = f"{API_BASE_URL}/historical/{date_str}.json"
    responses.add(
        responses.GET,
        url,
        json={"error": "Invalid API key"},
        status=401,
    )

    # Call the asset function and expect an exception
    with pytest.raises(Exception) as exchange_err:
        exchange_rates(mock_context, mock_config)

    assert "Failed to fetch exchange rates: 401" in str(exchange_err.value)


def test_exchange_rates_missing_app_id(mock_context):
    """Test handling of missing API key."""
    # Create config with empty app_id
    config = ExchangeRateConfig(app_id="", api_base_url=API_BASE_URL)

    # Call the asset function and expect a ValueError
    with pytest.raises(ValueError) as exchange_info:
        exchange_rates(mock_context, config)

    assert "Open Exchange Rates API key (app_id) is required" in str(exchange_info.value)


@responses.activate
def test_exchange_rates_empty_response(mock_config, mock_context):
    """Test handling of empty rates in response."""
    # Setup mock response with empty rates
    date_str = mock_context.partition_key
    url = f"{API_BASE_URL}/historical/{date_str}.json"
    responses.add(
        responses.GET,
        url,
        json={"base": "USD", "rates": {}},
        status=200,
    )

    # Call the asset function and expect an exception
    with pytest.raises(Exception) as exchange_info:
        exchange_rates(mock_context, mock_config)

    assert f"No rates found for {date_str}" in str(exchange_info.value)


@responses.activate
def test_exchange_rates_different_date(mock_api_response, mock_config):
    """Test fetching exchange rates for a different date."""
    # Create a context with a different partition key
    different_date = "2025-02-20"
    context = build_asset_context(partition_key=different_date)

    # Setup mock response
    url = f"{API_BASE_URL}/historical/{different_date}.json"
    responses.add(
        responses.GET,
        url,
        json=mock_api_response,
        status=200,
    )

    # Call the asset function
    result = exchange_rates(context, mock_config)

    # Verify the result
    assert result == mock_api_response["rates"]


@responses.activate
def test_exchange_rates_custom_api_url(mock_api_response, mock_context):
    """Test using a custom API base URL."""
    # Create config with custom API URL
    custom_url = "https://custom-api.example.com"
    config = ExchangeRateConfig(app_id="test_app_id", api_base_url=custom_url)

    # Setup mock response with custom URL
    date_str = mock_context.partition_key
    url = f"{custom_url}/historical/{date_str}.json"
    responses.add(
        responses.GET,
        url,
        json=mock_api_response,
        status=200,
    )

    # Call the asset function
    result = exchange_rates(mock_context, config)

    # Verify the result
    assert result == mock_api_response["rates"]
