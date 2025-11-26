from datetime import UTC, datetime
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.forecast.inputs import FetchHistoricalDataInputs, GenerateForecastInputs, StoreForecastInputs


@pytest.fixture
def mock_insight_results():
    return [
        {
            "data": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0, 111.0, 112.0, 113.0],
            "days": [
                "2024-01-01",
                "2024-01-02",
                "2024-01-03",
                "2024-01-04",
                "2024-01-05",
                "2024-01-06",
                "2024-01-07",
                "2024-01-08",
                "2024-01-09",
                "2024-01-10",
                "2024-01-11",
                "2024-01-12",
                "2024-01-13",
                "2024-01-14",
            ],
            "breakdown_value": "Chrome",
        },
        {
            "data": [200.0, 201.0, 202.0, 203.0, 204.0, 205.0, 206.0, 207.0, 208.0, 209.0, 210.0, 211.0, 212.0, 213.0],
            "days": [
                "2024-01-01",
                "2024-01-02",
                "2024-01-03",
                "2024-01-04",
                "2024-01-05",
                "2024-01-06",
                "2024-01-07",
                "2024-01-08",
                "2024-01-09",
                "2024-01-10",
                "2024-01-11",
                "2024-01-12",
                "2024-01-13",
                "2024-01-14",
            ],
            "breakdown_value": "Firefox",
        },
    ]


class TestFetchHistoricalDataActivity:
    @pytest.mark.asyncio
    @patch("posthog.hogql_queries.query_runner.get_query_runner")
    @patch("posthog.models.Insight")
    async def test_fetches_historical_data_for_single_series(
        self, mock_insight_model: MagicMock, mock_get_runner: MagicMock, mock_insight_results: list[dict]
    ) -> None:
        from posthog.temporal.forecast.activities import fetch_historical_data_activity

        mock_insight = MagicMock()
        mock_insight.query = {"kind": "TrendsQuery"}
        mock_insight.team = MagicMock()
        mock_insight_model.objects.select_related.return_value.get.return_value = mock_insight

        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.results = mock_insight_results
        mock_runner.calculate.return_value = mock_response
        mock_get_runner.return_value = mock_runner

        inputs = FetchHistoricalDataInputs(
            team_id=1,
            insight_id=1,
            series_indices=[0],
            min_historical_points=14,
        )

        result = await fetch_historical_data_activity(inputs)

        assert len(result) == 1
        assert result[0]["series_index"] == 0
        assert result[0]["breakdown_value"] == {"value": "Chrome"}
        assert len(result[0]["values"]) == 14

    @pytest.mark.asyncio
    @patch("posthog.hogql_queries.query_runner.get_query_runner")
    @patch("posthog.models.Insight")
    async def test_fetches_historical_data_for_multiple_series(
        self, mock_insight_model: MagicMock, mock_get_runner: MagicMock, mock_insight_results: list[dict]
    ) -> None:
        from posthog.temporal.forecast.activities import fetch_historical_data_activity

        mock_insight = MagicMock()
        mock_insight.query = {"kind": "TrendsQuery"}
        mock_insight.team = MagicMock()
        mock_insight_model.objects.select_related.return_value.get.return_value = mock_insight

        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.results = mock_insight_results
        mock_runner.calculate.return_value = mock_response
        mock_get_runner.return_value = mock_runner

        inputs = FetchHistoricalDataInputs(
            team_id=1,
            insight_id=1,
            series_indices=[0, 1],
            min_historical_points=14,
        )

        result = await fetch_historical_data_activity(inputs)

        assert len(result) == 2
        assert result[0]["breakdown_value"] == {"value": "Chrome"}
        assert result[1]["breakdown_value"] == {"value": "Firefox"}

    @pytest.mark.asyncio
    @patch("posthog.hogql_queries.query_runner.get_query_runner")
    @patch("posthog.models.Insight")
    async def test_skips_series_with_insufficient_data(
        self, mock_insight_model: MagicMock, mock_get_runner: MagicMock
    ) -> None:
        from posthog.temporal.forecast.activities import fetch_historical_data_activity

        mock_insight = MagicMock()
        mock_insight.query = {"kind": "TrendsQuery"}
        mock_insight.team = MagicMock()
        mock_insight_model.objects.select_related.return_value.get.return_value = mock_insight

        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.results = [
            {"data": [100.0, 101.0, 102.0], "days": ["2024-01-01", "2024-01-02", "2024-01-03"]},
        ]
        mock_runner.calculate.return_value = mock_response
        mock_get_runner.return_value = mock_runner

        inputs = FetchHistoricalDataInputs(
            team_id=1,
            insight_id=1,
            series_indices=[0],
            min_historical_points=14,
        )

        result = await fetch_historical_data_activity(inputs)

        assert len(result) == 0

    @pytest.mark.asyncio
    @patch("posthog.hogql_queries.query_runner.get_query_runner")
    @patch("posthog.models.Insight")
    async def test_skips_out_of_range_series_index(
        self, mock_insight_model: MagicMock, mock_get_runner: MagicMock, mock_insight_results: list[dict]
    ) -> None:
        from posthog.temporal.forecast.activities import fetch_historical_data_activity

        mock_insight = MagicMock()
        mock_insight.query = {"kind": "TrendsQuery"}
        mock_insight.team = MagicMock()
        mock_insight_model.objects.select_related.return_value.get.return_value = mock_insight

        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.results = mock_insight_results
        mock_runner.calculate.return_value = mock_response
        mock_get_runner.return_value = mock_runner

        inputs = FetchHistoricalDataInputs(
            team_id=1,
            insight_id=1,
            series_indices=[0, 5],  # 5 is out of range
            min_historical_points=14,
        )

        result = await fetch_historical_data_activity(inputs)

        assert len(result) == 1
        assert result[0]["series_index"] == 0

    @pytest.mark.asyncio
    @patch("posthog.hogql_queries.query_runner.get_query_runner")
    @patch("posthog.models.Insight")
    async def test_converts_none_values_to_zero(
        self, mock_insight_model: MagicMock, mock_get_runner: MagicMock
    ) -> None:
        from posthog.temporal.forecast.activities import fetch_historical_data_activity

        mock_insight = MagicMock()
        mock_insight.query = {"kind": "TrendsQuery"}
        mock_insight.team = MagicMock()
        mock_insight_model.objects.select_related.return_value.get.return_value = mock_insight

        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.results = [
            {
                "data": [
                    100.0,
                    None,
                    102.0,
                    103.0,
                    None,
                    105.0,
                    106.0,
                    107.0,
                    108.0,
                    109.0,
                    110.0,
                    111.0,
                    112.0,
                    113.0,
                ],
                "days": [
                    "2024-01-01",
                    "2024-01-02",
                    "2024-01-03",
                    "2024-01-04",
                    "2024-01-05",
                    "2024-01-06",
                    "2024-01-07",
                    "2024-01-08",
                    "2024-01-09",
                    "2024-01-10",
                    "2024-01-11",
                    "2024-01-12",
                    "2024-01-13",
                    "2024-01-14",
                ],
            },
        ]
        mock_runner.calculate.return_value = mock_response
        mock_get_runner.return_value = mock_runner

        inputs = FetchHistoricalDataInputs(
            team_id=1,
            insight_id=1,
            series_indices=[0],
            min_historical_points=14,
        )

        result = await fetch_historical_data_activity(inputs)

        assert result[0]["values"][1] == 0.0
        assert result[0]["values"][4] == 0.0


class TestGenerateForecastActivity:
    @pytest.mark.asyncio
    @patch("posthog.temporal.forecast.chronos_service.ChronosForecaster.compute_data_hash")
    @patch("posthog.temporal.forecast.chronos_service.ChronosForecaster.forecast")
    async def test_generates_forecast_for_single_series(self, mock_forecast: MagicMock, mock_hash: MagicMock) -> None:
        from posthog.temporal.forecast.activities import generate_forecast_activity

        mock_forecast.return_value = (100.0, 90.0, 110.0)
        mock_hash.return_value = "abc123"

        inputs = GenerateForecastInputs(
            historical_data=[
                {
                    "series_index": 0,
                    "breakdown_value": {"value": "Chrome"},
                    "timestamps": ["2024-01-01"],
                    "values": [100.0] * 14,
                }
            ],
            confidence_level=0.95,
            forecast_horizon=1,
        )

        result = await generate_forecast_activity(inputs)

        assert len(result) == 1
        assert result[0]["predicted_value"] == 100.0
        assert result[0]["lower_bound"] == 90.0
        assert result[0]["upper_bound"] == 110.0
        assert result[0]["confidence_level"] == 0.95
        mock_forecast.assert_called_once()

    @pytest.mark.asyncio
    @patch("posthog.temporal.forecast.chronos_service.ChronosForecaster.compute_data_hash")
    @patch("posthog.temporal.forecast.chronos_service.ChronosForecaster.forecast_batch")
    async def test_generates_batch_forecast_for_multiple_series(
        self, mock_forecast_batch: MagicMock, mock_hash: MagicMock
    ) -> None:
        from posthog.temporal.forecast.activities import generate_forecast_activity

        mock_forecast_batch.return_value = [
            (100.0, 90.0, 110.0),
            (200.0, 180.0, 220.0),
        ]
        mock_hash.return_value = "abc123"

        inputs = GenerateForecastInputs(
            historical_data=[
                {"series_index": 0, "breakdown_value": {"value": "Chrome"}, "values": [100.0] * 14},
                {"series_index": 1, "breakdown_value": {"value": "Firefox"}, "values": [200.0] * 14},
            ],
            confidence_level=0.95,
            forecast_horizon=1,
        )

        result = await generate_forecast_activity(inputs)

        assert len(result) == 2
        assert result[0]["predicted_value"] == 100.0
        assert result[1]["predicted_value"] == 200.0
        mock_forecast_batch.assert_called_once()

    @pytest.mark.asyncio
    @patch("posthog.temporal.forecast.chronos_service.ChronosForecaster.compute_data_hash")
    @patch("posthog.temporal.forecast.chronos_service.ChronosForecaster.forecast")
    async def test_includes_timestamp_in_forecast(self, mock_forecast: MagicMock, mock_hash: MagicMock) -> None:
        from posthog.temporal.forecast.activities import generate_forecast_activity

        mock_forecast.return_value = (100.0, 90.0, 110.0)
        mock_hash.return_value = "abc123"

        inputs = GenerateForecastInputs(
            historical_data=[{"series_index": 0, "values": [100.0] * 14}],
            confidence_level=0.95,
            forecast_horizon=1,
        )

        result = await generate_forecast_activity(inputs)

        assert "forecast_timestamp" in result[0]
        timestamp = datetime.fromisoformat(result[0]["forecast_timestamp"])
        assert timestamp.tzinfo is not None


class TestStoreForecastResultActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    @patch("posthog.models.alert.ForecastResult")
    @patch("posthog.models.alert.AlertConfiguration")
    async def test_stores_forecast_results(self, mock_alert_config: MagicMock, mock_forecast_result: MagicMock) -> None:
        from posthog.temporal.forecast.activities import store_forecast_result_activity

        mock_alert = MagicMock()
        mock_alert_config.objects.get.return_value = mock_alert
        mock_forecast_result.objects.filter.return_value.delete.return_value = None
        mock_forecast_result.objects.create.return_value = MagicMock()

        inputs = StoreForecastInputs(
            team_id=1,
            alert_id=str(uuid4()),
            forecasts=[
                {
                    "series_index": 0,
                    "breakdown_value": {"value": "Chrome"},
                    "forecast_timestamp": datetime.now(UTC).isoformat(),
                    "predicted_value": 100.0,
                    "lower_bound": 90.0,
                    "upper_bound": 110.0,
                    "confidence_level": 0.95,
                    "historical_data_hash": "abc123",
                }
            ],
        )

        result = await store_forecast_result_activity(inputs)

        assert result == 1
        mock_forecast_result.objects.create.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    @patch("posthog.models.alert.ForecastResult")
    @patch("posthog.models.alert.AlertConfiguration")
    async def test_deletes_existing_forecasts_before_storing(
        self, mock_alert_config: MagicMock, mock_forecast_result: MagicMock
    ) -> None:
        from posthog.temporal.forecast.activities import store_forecast_result_activity

        mock_alert = MagicMock()
        mock_alert_config.objects.get.return_value = mock_alert
        mock_delete = MagicMock()
        mock_forecast_result.objects.filter.return_value.delete = mock_delete

        inputs = StoreForecastInputs(
            team_id=1,
            alert_id=str(uuid4()),
            forecasts=[
                {
                    "series_index": 0,
                    "forecast_timestamp": datetime.now(UTC).isoformat(),
                    "predicted_value": 100.0,
                    "lower_bound": 90.0,
                    "upper_bound": 110.0,
                    "confidence_level": 0.95,
                    "historical_data_hash": "abc123",
                }
            ],
        )

        await store_forecast_result_activity(inputs)

        mock_forecast_result.objects.filter.assert_called_with(alert_configuration=mock_alert)
        mock_delete.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    @patch("posthog.models.alert.ForecastResult")
    @patch("posthog.models.alert.AlertConfiguration")
    async def test_stores_multiple_forecasts(
        self, mock_alert_config: MagicMock, mock_forecast_result: MagicMock
    ) -> None:
        from posthog.temporal.forecast.activities import store_forecast_result_activity

        mock_alert = MagicMock()
        mock_alert_config.objects.get.return_value = mock_alert
        mock_forecast_result.objects.filter.return_value.delete.return_value = None

        inputs = StoreForecastInputs(
            team_id=1,
            alert_id=str(uuid4()),
            forecasts=[
                {
                    "series_index": i,
                    "forecast_timestamp": datetime.now(UTC).isoformat(),
                    "predicted_value": 100.0 * (i + 1),
                    "lower_bound": 90.0 * (i + 1),
                    "upper_bound": 110.0 * (i + 1),
                    "confidence_level": 0.95,
                    "historical_data_hash": f"hash{i}",
                }
                for i in range(3)
            ],
        )

        result = await store_forecast_result_activity(inputs)

        assert result == 3
        assert mock_forecast_result.objects.create.call_count == 3
