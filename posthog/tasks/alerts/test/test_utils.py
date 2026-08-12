from datetime import UTC, datetime

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import AlertCalculationInterval

from posthog.slo.context import SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation, SloOutcome
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
    @patch("posthog.tasks.alerts.utils.alert_internal_event_delivered", return_value=True)
    @patch("posthog.tasks.alerts.utils.flush_alert_internal_events")
    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event")
    def test_trigger_alert_hog_functions_uses_shared_delivery(
        self,
        _name: str,
        detector_config: dict | None,
        expected_props: dict,
        mock_produce: MagicMock,
        mock_flush: MagicMock,
        mock_delivered: MagicMock,
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
        mock_flush.assert_not_called()
        mock_delivered.assert_not_called()

    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event", return_value=None)
    def test_trigger_alert_hog_functions_ignores_enqueue_failure(self, _mock_produce: MagicMock) -> None:
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.team_id = 2
        alert.last_checked_at = None
        alert.detector_config = None

        trigger_alert_hog_functions(alert, properties={"breaches": "test breach"})

    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event", return_value=None)
    def test_destination_enqueue_failure_fails_delivery_slo(self, _mock_produce: MagicMock) -> None:
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.name = "test alert"
        alert.insight.name = "test insight"
        alert.insight.short_id = "abcd1234"
        alert.state = "firing"
        alert.last_checked_at = None
        alert.team_id = 2
        alert.team.name = "test project"
        alert.detector_config = None
        capture = MagicMock()

        with slo_operation(
            spec=SloSpec(
                distinct_id=str(alert.id),
                area=SloArea.ANALYTIC_PLATFORM,
                operation=SloOperation.ALERT_DELIVERY,
                team_id=alert.team_id,
                resource_id=str(alert.id),
            ),
            capture=capture,
        ):
            trigger_alert_hog_functions(alert, properties={"breaches": "test breach"})

        completed = [call for call in capture.call_args_list if call.kwargs["event"] == "slo_operation_completed"]
        assert len(completed) == 1
        assert completed[0].kwargs["properties"]["outcome"] == SloOutcome.FAILURE
        assert completed[0].kwargs["properties"]["failure_phase"] == "destination_enqueue"

    @patch("posthog.tasks.alerts.utils.alert_internal_event_delivered", return_value=False)
    @patch("posthog.tasks.alerts.utils.flush_alert_internal_events")
    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event")
    def test_destination_delivery_failure_fails_delivery_slo(
        self,
        mock_produce: MagicMock,
        mock_flush: MagicMock,
        _mock_delivered: MagicMock,
    ) -> None:
        produce_result = MagicMock()
        mock_produce.return_value = produce_result
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.name = "test alert"
        alert.insight.name = "test insight"
        alert.insight.short_id = "abcd1234"
        alert.state = "firing"
        alert.last_checked_at = None
        alert.team_id = 2
        alert.team.name = "test project"
        alert.detector_config = None
        capture = MagicMock()

        with slo_operation(
            spec=SloSpec(
                distinct_id=str(alert.id),
                area=SloArea.ANALYTIC_PLATFORM,
                operation=SloOperation.ALERT_DELIVERY,
                team_id=alert.team_id,
                resource_id=str(alert.id),
            ),
            capture=capture,
        ):
            trigger_alert_hog_functions(alert, properties={"breaches": "test breach"})

        mock_flush.assert_called_once_with(10.0)
        completed = [call for call in capture.call_args_list if call.kwargs["event"] == "slo_operation_completed"]
        assert len(completed) == 1
        assert completed[0].kwargs["properties"]["outcome"] == SloOutcome.FAILURE
        assert completed[0].kwargs["properties"]["failure_phase"] == "notification_delivery"
