from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import ValidationError

from products.alerts.backend.destinations import (
    alert_internal_event_delivered,
    soft_delete_alert_destinations,
    soft_delete_all_alert_destinations,
)
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

ALLOWED_EVENT_IDS = ("$logs_alert_firing", "$logs_alert_resolved")


class TestSoftDeleteAlertDestinations(APIBaseTest):
    def _make_hog_function(
        self, *, template_id: str, alert_id: str, event_id: str = "$logs_alert_firing"
    ) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name="Test destination",
            type="destination",
            template_id=template_id,
            enabled=True,
            inputs_schema=[],
            inputs={},
            hog="return event",
            filters={
                "events": [{"id": event_id, "type": "events"}],
                "properties": [{"key": "alert_id", "value": alert_id}],
            },
        )

    def test_deletes_alert_destination_with_matching_alert_id(self) -> None:
        destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")

        soft_delete_alert_destinations(
            team_id=self.team.id,
            alert_id="alert-1",
            allowed_event_ids=ALLOWED_EVENT_IDS,
            hog_function_ids=[destination.id],
        )

        destination.refresh_from_db()
        assert destination.deleted is True
        assert destination.enabled is False

    def test_reports_invalid_ids_and_does_not_delete_any_destinations(self) -> None:
        destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")
        other = self._make_hog_function(template_id="template-webhook", alert_id="alert-1", event_id="$unrelated_event")

        with self.assertRaises(ValidationError) as error:
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id, other.id],
            )

        assert isinstance(error.exception.detail, dict)
        hog_function_id_errors = error.exception.detail["hog_function_ids"]
        assert isinstance(hog_function_id_errors, list)
        assert str(hog_function_id_errors[0]) == (
            f"These HogFunctions do not belong to this alert: {other.id}. Refresh the alert and try again."
        )
        for hog_function in (destination, other):
            hog_function.refresh_from_db()
            assert hog_function.deleted is False
            assert hog_function.enabled is True

    def test_deletes_all_destinations_for_alert_only(self) -> None:
        slack_destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")
        webhook_destination = self._make_hog_function(template_id="template-webhook", alert_id="alert-1")
        other_alert_destination = self._make_hog_function(template_id="template-slack", alert_id="alert-2")
        non_destination = self._make_hog_function(template_id="template-webhook-custom", alert_id="alert-1")
        unrelated_event_destination = self._make_hog_function(
            template_id="template-webhook", alert_id="alert-1", event_id="$unrelated_event"
        )

        deleted_count = soft_delete_all_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=ALLOWED_EVENT_IDS
        )

        assert deleted_count == 2
        for destination in (slack_destination, webhook_destination):
            destination.refresh_from_db()
            assert destination.deleted is True
            assert destination.enabled is False

        for destination in (other_alert_destination, non_destination, unrelated_event_destination):
            destination.refresh_from_db()
            assert destination.deleted is False
            assert destination.enabled is True

    def test_rejects_empty_allowed_event_ids_without_deleting_destinations(self) -> None:
        destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")

        with self.assertRaisesRegex(ValueError, "allowed_event_ids must not be empty"):
            soft_delete_all_alert_destinations(team_id=self.team.id, alert_id="alert-1", allowed_event_ids=())

        destination.refresh_from_db()
        assert destination.deleted is False
        assert destination.enabled is True

    @patch("products.alerts.backend.destinations.reload_hog_functions_on_workers")
    def test_reload_happens_after_destination_delete_commits(self, reload_hog_functions_on_workers) -> None:
        destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")

        with self.captureOnCommitCallbacks(execute=True):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id],
            )
            reload_hog_functions_on_workers.assert_not_called()

        reload_hog_functions_on_workers.assert_called_once_with(
            team_id=self.team.id, hog_function_ids=[str(destination.id)]
        )

    @patch("products.alerts.backend.destinations.reload_hog_functions_on_workers", side_effect=RuntimeError("boom"))
    def test_reload_failure_does_not_fail_committed_delete(self, _reload_hog_functions_on_workers) -> None:
        destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")

        with self.captureOnCommitCallbacks(execute=True):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id],
            )

        destination.refresh_from_db()
        assert destination.deleted is True
        assert destination.enabled is False


class TestAlertInternalEventDelivery(APIBaseTest):
    @patch("products.alerts.backend.destinations.capture_exception")
    @patch("products.alerts.backend.destinations.ALERT_INTERNAL_EVENT_DELIVERY_FAILURES")
    def test_expected_delivery_failure_records_metric_without_capturing_exception(
        self, delivery_failures, capture_exception
    ) -> None:
        produce_result = MagicMock()
        produce_result.get.side_effect = RuntimeError("delivery failed")

        delivered = alert_internal_event_delivered(
            produce_result,
            team_id=self.team.id,
            alert_id="alert-1",
            event_name="$logs_alert_firing",
        )

        assert delivered is False
        capture_exception.assert_not_called()
        delivery_failures.labels.assert_called_once_with(event_name="$logs_alert_firing")
        delivery_failures.labels.return_value.inc.assert_called_once_with()
