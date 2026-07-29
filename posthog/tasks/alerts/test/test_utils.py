from datetime import UTC, datetime

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import AlertCalculationInterval

from posthog.tasks.alerts.utils import calculation_interval_to_order, next_check_time, trigger_alert_hog_functions

from products.alerts.backend.models.alert import AlertConfiguration


class TestAlertUtils:
    def test_calculation_interval_to_order_ranks_real_time_first(self) -> None:
        assert calculation_interval_to_order(AlertCalculationInterval.REAL_TIME) < calculation_interval_to_order(
            AlertCalculationInterval.EVERY_15_MINUTES
        )

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

    @parameterized.expand(
        [
            ("threshold", None, {"alert_mode": "threshold", "detector_type": None, "ensemble_operator": None}),
            (
                "detector",
                {"type": "zscore", "threshold": 0.95, "window": 30},
                {"alert_mode": "detector", "detector_type": "zscore", "ensemble_operator": None},
            ),
            (
                "ensemble",
                {
                    "type": "ensemble",
                    "operator": "AND",
                    "detectors": [
                        {"type": "zscore", "threshold": 0.95, "window": 30},
                        {"type": "mad", "threshold": 0.95, "window": 30},
                    ],
                },
                {"alert_mode": "detector", "detector_type": "ensemble", "ensemble_operator": "AND"},
            ),
        ]
    )
    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event")
    def test_trigger_alert_hog_functions_uses_shared_delivery(
        self,
        _name: str,
        detector_config: dict | None,
        expected_props: dict,
        mock_produce: MagicMock,
    ) -> None:
        mock_produce.return_value = MagicMock()
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.name = "test alert"
        alert.insight.name = "test insight"
        alert.insight.short_id = "abcd1234"
        alert.state = "firing"
        alert.last_checked_at = None
        alert.team_id = 2
        alert.team.name = "test project"
        alert.detector_config = detector_config

        trigger_alert_hog_functions(alert, properties={"breaches": "test breach"})

        props = mock_produce.call_args.kwargs["properties"]
        for key, expected_value in expected_props.items():
            assert props[key] == expected_value
        assert props["breaches"] == "test breach"
        assert "uuid" not in mock_produce.call_args.kwargs

    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event", return_value=None)
    def test_trigger_alert_hog_functions_ignores_enqueue_failure(self, _mock_produce: MagicMock) -> None:
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.team_id = 2
        alert.last_checked_at = None
        alert.detector_config = None

        trigger_alert_hog_functions(alert, properties={"breaches": "test breach"})
