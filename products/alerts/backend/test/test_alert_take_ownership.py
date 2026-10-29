from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.test.insight_alerts import create_insight_alert


class TestAlertTakeOwnership(APIBaseTest):
    def _disabled_alert_of_a_former_member(self) -> AlertConfiguration:
        former_member = User.objects.create_user(email="former-member@example.com", first_name="", password=None)
        return create_insight_alert(self.team, created_by=former_member, enabled=False)

    def test_enabling_is_rejected_when_the_owner_left(self) -> None:
        alert = self._disabled_alert_of_a_former_member()

        response = self.client.patch(f"/api/projects/{self.team.id}/alerts/{alert.id}", {"enabled": True})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.json()["attr"] == "enabled"
        # The frontend keys its "take ownership" offer on this code.
        assert response.json()["code"] == "owner_unavailable"

    def test_take_ownership_enables_the_alert_as_the_requester(self) -> None:
        alert = self._disabled_alert_of_a_former_member()

        response = self.client.post(f"/api/projects/{self.team.id}/alerts/{alert.id}/take-ownership/")

        assert response.status_code == status.HTTP_200_OK, response.content
        alert.refresh_from_db()
        assert alert.created_by == self.user
        assert alert.enabled is True
        # created_by is excluded from the save diff, so the takeover logs its own activity.
        takeover = ActivityLog.objects.get(scope="AlertConfiguration", item_id=str(alert.id), activity="took_ownership")
        assert [change["field"] for change in takeover.detail["changes"]] == ["created_by"]
        assert takeover.user == self.user
