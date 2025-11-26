from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import IntervalType, TrendsQuery

from posthog.models.alert import AlertConfiguration
from posthog.tasks.alerts.forecast import (
    _date_range_override_for_current_value,
    check_forecast_alert,
    check_forecast_alert_multi_series,
)


class TestDateRangeOverride(BaseTest):
    @parameterized.expand(
        [
            (IntervalType.HOUR, "-2h"),
            (IntervalType.DAY, "-2d"),
            (IntervalType.WEEK, "-2w"),
            (IntervalType.MONTH, "-2m"),
        ]
    )
    def test_date_range_override_for_interval(self, interval: IntervalType, expected_from: str) -> None:
        query = MagicMock(spec=TrendsQuery)
        query.interval = interval

        result = _date_range_override_for_current_value(query)

        assert result["date_from"] == expected_from
        assert result["date_to"] is None


class TestCheckForecastAlert(BaseTest):
    def setUp(self) -> None:
        super().setUp()

        self.insight = MagicMock()
        self.insight.id = 1

        self.query = MagicMock(spec=TrendsQuery)
        self.query.interval = IntervalType.DAY

        self.alert = MagicMock(spec=AlertConfiguration)
        self.alert.id = uuid4()
        self.alert.team = self.team
        self.alert.config = {"type": "ForecastAlertConfig", "series_index": 0, "confidence_level": 0.95}

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_no_forecast_available(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        mock_forecast_objects.filter.return_value.order_by.return_value.first.return_value = None

        result = check_forecast_alert(self.alert, self.insight, self.query)

        assert result.value is None
        assert result.breaches is not None
        assert "No forecast available" in result.breaches[0]
        mock_calculate.assert_not_called()

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_value_within_bounds_no_breach(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        mock_forecast = MagicMock()
        mock_forecast.lower_bound = 90.0
        mock_forecast.upper_bound = 110.0
        mock_forecast.predicted_value = 100.0
        mock_forecast.confidence_level = 0.95
        mock_forecast_objects.filter.return_value.order_by.return_value.first.return_value = mock_forecast

        mock_result = MagicMock()
        mock_result.result = [{"data": [95, 100, 105]}]
        mock_calculate.return_value = mock_result

        result = check_forecast_alert(self.alert, self.insight, self.query)

        assert result.value == 105.0
        assert result.breaches is None

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_value_below_lower_bound_breach(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        mock_forecast = MagicMock()
        mock_forecast.lower_bound = 90.0
        mock_forecast.upper_bound = 110.0
        mock_forecast.predicted_value = 100.0
        mock_forecast.confidence_level = 0.95
        mock_forecast_objects.filter.return_value.order_by.return_value.first.return_value = mock_forecast

        mock_result = MagicMock()
        mock_result.result = [{"data": [95, 100, 80]}]  # 80 is below lower bound of 90
        mock_calculate.return_value = mock_result

        result = check_forecast_alert(self.alert, self.insight, self.query)

        assert result.value == 80.0
        assert result.breaches is not None
        assert len(result.breaches) == 1
        assert "below forecast lower bound" in result.breaches[0]
        assert "80.00" in result.breaches[0]
        assert "90.00" in result.breaches[0]

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_value_above_upper_bound_breach(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        mock_forecast = MagicMock()
        mock_forecast.lower_bound = 90.0
        mock_forecast.upper_bound = 110.0
        mock_forecast.predicted_value = 100.0
        mock_forecast.confidence_level = 0.95
        mock_forecast_objects.filter.return_value.order_by.return_value.first.return_value = mock_forecast

        mock_result = MagicMock()
        mock_result.result = [{"data": [95, 100, 120]}]  # 120 is above upper bound of 110
        mock_calculate.return_value = mock_result

        result = check_forecast_alert(self.alert, self.insight, self.query)

        assert result.value == 120.0
        assert result.breaches is not None
        assert len(result.breaches) == 1
        assert "above forecast upper bound" in result.breaches[0]
        assert "120.00" in result.breaches[0]
        assert "110.00" in result.breaches[0]

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_no_data_available(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        mock_forecast = MagicMock()
        mock_forecast.lower_bound = 90.0
        mock_forecast.upper_bound = 110.0
        mock_forecast_objects.filter.return_value.order_by.return_value.first.return_value = mock_forecast

        mock_result = MagicMock()
        mock_result.result = [{"data": []}]
        mock_calculate.return_value = mock_result

        result = check_forecast_alert(self.alert, self.insight, self.query)

        assert result.value is None
        assert result.breaches is not None
        assert "No data available" in result.breaches[0]

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_series_index_out_of_range(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        self.alert.config = {"type": "ForecastAlertConfig", "series_index": 5, "confidence_level": 0.95}

        mock_forecast = MagicMock()
        mock_forecast_objects.filter.return_value.order_by.return_value.first.return_value = mock_forecast

        mock_result = MagicMock()
        mock_result.result = [{"data": [100]}]  # Only one series
        mock_calculate.return_value = mock_result

        with pytest.raises(ValueError, match="Series index 5 is out of range"):
            check_forecast_alert(self.alert, self.insight, self.query)

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_none_value_treated_as_zero(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        mock_forecast = MagicMock()
        mock_forecast.lower_bound = 10.0
        mock_forecast.upper_bound = 100.0
        mock_forecast.predicted_value = 50.0
        mock_forecast.confidence_level = 0.95
        mock_forecast_objects.filter.return_value.order_by.return_value.first.return_value = mock_forecast

        mock_result = MagicMock()
        mock_result.result = [{"data": [95, 100, None]}]  # None value
        mock_calculate.return_value = mock_result

        result = check_forecast_alert(self.alert, self.insight, self.query)

        assert result.value == 0.0
        assert result.breaches is not None
        assert "below forecast lower bound" in result.breaches[0]


class TestCheckForecastAlertMultiSeries(BaseTest):
    def setUp(self) -> None:
        super().setUp()

        self.insight = MagicMock()
        self.insight.id = 1

        self.query = MagicMock(spec=TrendsQuery)
        self.query.interval = IntervalType.DAY

        self.alert = MagicMock(spec=AlertConfiguration)
        self.alert.id = uuid4()
        self.alert.team = self.team

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_no_forecasts_available(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        mock_forecast_objects.filter.return_value.order_by.return_value.distinct.return_value.__getitem__.return_value = []

        result = check_forecast_alert_multi_series(self.alert, self.insight, self.query)

        assert result.value is None
        assert result.breaches is not None
        assert "No forecasts available" in result.breaches[0]
        mock_calculate.assert_not_called()

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_all_series_within_bounds(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        forecast1 = MagicMock()
        forecast1.series_index = 0
        forecast1.lower_bound = 90.0
        forecast1.upper_bound = 110.0

        forecast2 = MagicMock()
        forecast2.series_index = 1
        forecast2.lower_bound = 190.0
        forecast2.upper_bound = 210.0

        mock_forecast_objects.filter.return_value.order_by.return_value.distinct.return_value.__getitem__.return_value = [
            forecast1,
            forecast2,
        ]

        mock_result = MagicMock()
        mock_result.result = [
            {"data": [100], "breakdown_value": "Chrome"},
            {"data": [200], "breakdown_value": "Firefox"},
        ]
        mock_calculate.return_value = mock_result

        result = check_forecast_alert_multi_series(self.alert, self.insight, self.query)

        assert result.value == 100.0
        assert result.breaches is None

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_one_series_breaches(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        forecast1 = MagicMock()
        forecast1.series_index = 0
        forecast1.lower_bound = 90.0
        forecast1.upper_bound = 110.0

        forecast2 = MagicMock()
        forecast2.series_index = 1
        forecast2.lower_bound = 190.0
        forecast2.upper_bound = 210.0

        mock_forecast_objects.filter.return_value.order_by.return_value.distinct.return_value.__getitem__.return_value = [
            forecast1,
            forecast2,
        ]

        mock_result = MagicMock()
        mock_result.result = [
            {"data": [100], "breakdown_value": "Chrome"},
            {"data": [250], "breakdown_value": "Firefox"},  # Above upper bound
        ]
        mock_calculate.return_value = mock_result

        result = check_forecast_alert_multi_series(self.alert, self.insight, self.query)

        assert result.value == 100.0
        assert result.breaches is not None
        assert len(result.breaches) == 1
        assert "[Firefox]" in result.breaches[0]
        assert "above forecast upper bound" in result.breaches[0]

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_multiple_series_breach(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        forecast1 = MagicMock()
        forecast1.series_index = 0
        forecast1.lower_bound = 90.0
        forecast1.upper_bound = 110.0

        forecast2 = MagicMock()
        forecast2.series_index = 1
        forecast2.lower_bound = 190.0
        forecast2.upper_bound = 210.0

        mock_forecast_objects.filter.return_value.order_by.return_value.distinct.return_value.__getitem__.return_value = [
            forecast1,
            forecast2,
        ]

        mock_result = MagicMock()
        mock_result.result = [
            {"data": [50], "breakdown_value": "Chrome"},  # Below lower bound
            {"data": [250], "breakdown_value": "Firefox"},  # Above upper bound
        ]
        mock_calculate.return_value = mock_result

        result = check_forecast_alert_multi_series(self.alert, self.insight, self.query)

        assert result.value == 50.0
        assert result.breaches is not None
        assert len(result.breaches) == 2
        assert any("[Chrome]" in b and "below" in b for b in result.breaches)
        assert any("[Firefox]" in b and "above" in b for b in result.breaches)

    @patch("posthog.tasks.alerts.forecast.calculate_for_query_based_insight")
    @patch("posthog.tasks.alerts.forecast.ForecastResult.objects")
    def test_skips_out_of_range_series(self, mock_forecast_objects: MagicMock, mock_calculate: MagicMock) -> None:
        forecast1 = MagicMock()
        forecast1.series_index = 0
        forecast1.lower_bound = 90.0
        forecast1.upper_bound = 110.0

        forecast2 = MagicMock()
        forecast2.series_index = 5  # Out of range
        forecast2.lower_bound = 190.0
        forecast2.upper_bound = 210.0

        mock_forecast_objects.filter.return_value.order_by.return_value.distinct.return_value.__getitem__.return_value = [
            forecast1,
            forecast2,
        ]

        mock_result = MagicMock()
        mock_result.result = [{"data": [100], "breakdown_value": "Chrome"}]  # Only one series
        mock_calculate.return_value = mock_result

        result = check_forecast_alert_multi_series(self.alert, self.insight, self.query)

        assert result.value == 100.0
        assert result.breaches is None
