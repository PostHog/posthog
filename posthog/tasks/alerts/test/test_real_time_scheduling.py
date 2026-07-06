from datetime import UTC, datetime

from freezegun import freeze_time
from unittest.mock import MagicMock

from posthog.schema import AlertCalculationInterval

from posthog.tasks.alerts.utils import (
    alert_calculation_interval_to_relativedelta,
    calculation_interval_to_order,
    next_check_time,
)

from products.alerts.backend.models.alert import AlertConfiguration


class TestAlertRealTimeScheduling:
    def test_calculation_interval_to_order_ranks_real_time_first(self) -> None:
        assert calculation_interval_to_order(AlertCalculationInterval.REAL_TIME) < calculation_interval_to_order(
            AlertCalculationInterval.EVERY_15_MINUTES
        )

    def test_alert_calculation_interval_to_relativedelta_real_time(self) -> None:
        delta = alert_calculation_interval_to_relativedelta(AlertCalculationInterval.REAL_TIME)
        assert delta.minutes == 2

    def test_next_check_time_advances_by_2_minutes(self) -> None:
        alert = MagicMock(spec=AlertConfiguration)
        alert.calculation_interval = AlertCalculationInterval.REAL_TIME
        alert.next_check_at = datetime(2026, 4, 6, 14, 0, 0, tzinfo=UTC)
        alert.team = MagicMock()
        alert.team.timezone = "UTC"
        alert.schedule_restriction = None
        alert.skip_weekend = False

        with freeze_time("2026-04-06T14:00:00Z"):
            assert next_check_time(alert) == datetime(2026, 4, 6, 14, 2, 0, tzinfo=UTC)
