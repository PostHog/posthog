from posthog.test.base import APIBaseTest

from products.alerts.backend.destinations import (
    AlertDestinationOwnershipError,
    soft_delete_alert_destinations,
    soft_delete_all_alert_destinations,
)
from products.cdp.backend.models.hog_functions.hog_function import HogFunction


class TestSoftDeleteAlertDestinations(APIBaseTest):
    def _make_hog_function(self, *, template_id: str, alert_id: str) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name="Test destination",
            type="destination",
            template_id=template_id,
            enabled=True,
            inputs_schema=[],
            inputs={},
            hog="return event",
            filters={"properties": [{"key": "alert_id", "value": alert_id}]},
        )

    def test_deletes_alert_destination_with_matching_alert_id(self) -> None:
        destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")

        soft_delete_alert_destinations(team_id=self.team.id, alert_id="alert-1", hog_function_ids=[destination.id])

        destination.refresh_from_db()
        assert destination.deleted is True
        assert destination.enabled is False

    def test_reports_invalid_ids_and_does_not_delete_any_destinations(self) -> None:
        destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")
        other = self._make_hog_function(template_id="template-webhook-custom", alert_id="alert-1")

        with self.assertRaises(AlertDestinationOwnershipError) as error:
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                hog_function_ids=[destination.id, other.id],
            )

        assert error.exception.invalid_hog_function_ids == (other.id,)
        for hog_function in (destination, other):
            hog_function.refresh_from_db()
            assert hog_function.deleted is False
            assert hog_function.enabled is True

    def test_deletes_all_destinations_for_alert_only(self) -> None:
        slack_destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")
        webhook_destination = self._make_hog_function(template_id="template-webhook", alert_id="alert-1")
        other_alert_destination = self._make_hog_function(template_id="template-slack", alert_id="alert-2")
        non_destination = self._make_hog_function(template_id="template-webhook-custom", alert_id="alert-1")

        deleted_count = soft_delete_all_alert_destinations(team_id=self.team.id, alert_id="alert-1")

        assert deleted_count == 2
        for destination in (slack_destination, webhook_destination):
            destination.refresh_from_db()
            assert destination.deleted is True
            assert destination.enabled is False

        for destination in (other_alert_destination, non_destination):
            destination.refresh_from_db()
            assert destination.deleted is False
            assert destination.enabled is True
