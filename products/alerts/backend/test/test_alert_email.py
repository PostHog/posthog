from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.cdp.internal_events import LEGACY_INSIGHT_ALERT_EVENT
from posthog.models.user import User

from products.alerts.backend.facade.destinations import list_alert_destination_groups, list_delivery_destination_groups
from products.alerts.backend.logic.alert_email import INSIGHT_ALERT_ERRORED_EVENT_ID
from products.alerts.backend.models.alert import AlertConfiguration, AlertSubscription
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade.contracts import DestinationType


class TestInsightAlertEmailDestination(APIBaseTest):
    def _alert(self) -> AlertConfiguration:
        return create_insight_alert(self.team)

    def _subscribe(self, alert: AlertConfiguration, user: User) -> None:
        AlertSubscription.objects.create(user=user, alert_configuration=alert)

    @parameterized.expand([("firing", LEGACY_INSIGHT_ALERT_EVENT), ("errored", INSIGHT_ALERT_ERRORED_EVENT_ID)])
    def test_the_platform_reaches_the_subscribers_production_reaches(self, _name: str, event_id: str) -> None:
        alert = self._alert()
        self._subscribe(alert, self.user)
        former_member = User.objects.create(email="former-member@example.com")
        self._subscribe(alert, former_member)
        firing = event_id == LEGACY_INSIGHT_ALERT_EVENT
        short_id = alert.insight.short_id

        groups = list_delivery_destination_groups(
            team_id=self.team.id, alert_id=str(alert.id), allowed_event_ids=[event_id]
        )

        # Production notifies every subscriber in the app when an alert fires, and only those who
        # can still see the alert when a check fails.
        assert [group.data for group in groups] == [
            {"type": DestinationType.EMAIL, "email_addresses": [self.user.email]},
            {
                "type": DestinationType.IN_APP,
                "in_app_user_ids": sorted([self.user.id, former_member.id]) if firing else [self.user.id],
                "in_app_resource_type": "insight",
                "in_app_resource_id": short_id,
                "in_app_url": f"/project/{self.team.project_id}/insights/{short_id}#alert={alert.id}"
                if firing
                else f"/project/{self.team.id}/insights/{short_id}?alert_id={alert.id}",
            },
        ]
        # The alert APIs list and delete through this one, so a subscriber group there would read as a
        # destination a person could remove.
        assert (
            list_alert_destination_groups(team_id=self.team.id, alert_id=str(alert.id), allowed_event_ids=[event_id])
            == []
        )

    @parameterized.expand(
        [
            ("another_sources_event", True, None, "$logs_alert_firing"),
            ("an_alert_id_that_is_not_an_insight_alert", True, "legacy-logs-alert", LEGACY_INSIGHT_ALERT_EVENT),
            ("an_alert_nobody_subscribed_to", False, None, LEGACY_INSIGHT_ALERT_EVENT),
        ]
    )
    def test_no_subscriber_group_without_an_insight_alert_and_a_subscriber(
        self, _name: str, subscribed: bool, alert_id: str | None, event_id: str
    ) -> None:
        alert = self._alert()
        if subscribed:
            self._subscribe(alert, self.user)

        groups = list_delivery_destination_groups(
            team_id=self.team.id, alert_id=alert_id or str(alert.id), allowed_event_ids=[event_id]
        )

        assert groups == []
