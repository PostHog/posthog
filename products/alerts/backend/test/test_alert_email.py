import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.facade.destinations import (
    list_alert_destination_groups,
    list_delivery_destination_groups,
    register_email_recipient_resolver,
)
from products.alerts.backend.logic import alert_email
from products.alerts.backend.logic.alert_email import INSIGHT_ALERT_ERRORED_EVENT_ID
from products.alerts.backend.models.alert import AlertConfiguration, AlertSubscription
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade.contracts import DestinationType
from products.cdp.backend.internal_events import LEGACY_INSIGHT_ALERT_EVENT


class TestInsightAlertEmailDestination(APIBaseTest):
    def _alert(self) -> AlertConfiguration:
        return create_insight_alert(self.team)

    def _subscribe(self, alert: AlertConfiguration, user: User) -> None:
        AlertSubscription.objects.create(user=user, alert_configuration=alert)

    @parameterized.expand([("firing", LEGACY_INSIGHT_ALERT_EVENT), ("errored", INSIGHT_ALERT_ERRORED_EVENT_ID)])
    def test_the_platform_reaches_only_subscribers_who_can_still_see_the_insight(
        self, _name: str, event_id: str
    ) -> None:
        alert = self._alert()
        self._subscribe(alert, self.user)
        self._subscribe(alert, User.objects.create(email="former-member@example.com"))
        denied = User.objects.create_and_join(self.organization, "denied@example.com", None)
        self._subscribe(alert, denied)
        firing = event_id == LEGACY_INSIGHT_ALERT_EVENT
        short_id = alert.insight.short_id

        def can_view(access_control: UserAccessControl, *_args: object) -> bool:
            return access_control._user.id != denied.id

        with patch.object(UserAccessControl, "check_access_level_for_object", autospec=True, side_effect=can_view):
            groups = list_delivery_destination_groups(
                team_id=self.team.id, alert_id=str(alert.id), allowed_event_ids=[event_id]
            )

        assert [group.data for group in groups] == [
            {"type": DestinationType.EMAIL, "email_addresses": [self.user.email]},
            {
                "type": DestinationType.IN_APP,
                "in_app_user_ids": [self.user.id],
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


class TestEmailRecipientRegistration(SimpleTestCase):
    @staticmethod
    def _nobody(*, team_id: int, alert_id: str) -> list[str]:
        return []

    @staticmethod
    def _somebody(*, team_id: int, alert_id: str) -> list[str]:
        return ["someone@example.com"]

    @parameterized.expand(
        [
            ("an_event_another_source_registered", "$registered_firing", "already registered"),
            ("an_insight_subscriber_event", LEGACY_INSIGHT_ALERT_EVENT, "subscribers of an insight alert"),
        ]
    )
    def test_a_second_owner_for_an_event_is_refused(self, _name: str, event_id: str, message: str) -> None:
        with patch.dict(alert_email._recipient_resolvers, clear=True):
            register_email_recipient_resolver(event_ids=["$registered_firing"], resolver=self._nobody)
            # Registering the same resolver again, as a second `ready()` does, is not a conflict.
            register_email_recipient_resolver(event_ids=["$registered_firing"], resolver=self._nobody)

            with pytest.raises(RuntimeError, match=message):
                register_email_recipient_resolver(event_ids=["$unclaimed", event_id], resolver=self._somebody)

            assert alert_email._recipient_resolvers == {"$registered_firing": self._nobody}
