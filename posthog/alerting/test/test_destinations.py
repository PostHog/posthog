from posthog.test.base import APIBaseTest

from posthog.alerting.destinations import (
    ALERT_ID_PROPERTY,
    AlertDestinationOwnershipError,
    soft_delete_alert_destinations,
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
            filters={"properties": [{"key": ALERT_ID_PROPERTY, "value": alert_id}]},
        )

    def test_deletes_alert_destination_with_matching_alert_id(self) -> None:
        destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")

        soft_delete_alert_destinations(team_id=self.team.id, alert_id="alert-1", hog_function_ids=[destination.id])

        destination.refresh_from_db()
        assert destination.deleted is True
        assert destination.enabled is False

    def test_raises_and_does_not_delete_non_destination_hog_function_with_matching_alert_id(self) -> None:
        # A same-team automation that happens to filter on a property named
        # "alert_id" for unrelated reasons — not one of the alert destination
        # templates. Must not be soft-deletable via the alert's delete path.
        other = self._make_hog_function(template_id="template-webhook-custom", alert_id="alert-1")

        with self.assertRaises(AlertDestinationOwnershipError):
            soft_delete_alert_destinations(team_id=self.team.id, alert_id="alert-1", hog_function_ids=[other.id])

        other.refresh_from_db()
        assert other.deleted is False
        assert other.enabled is True
