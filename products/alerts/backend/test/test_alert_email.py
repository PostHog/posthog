from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.facade.destinations import list_delivery_destination_groups
from products.alerts.backend.logic.alert_email import INSIGHT_ALERT_ERRORED_EVENT_ID
from products.alerts.backend.models.alert import AlertConfiguration, AlertSubscription
from products.alerts.backend.platform_hooks import insight_alert_creator, insight_alert_viewer
from products.alerts.backend.platform_insight_alert import subscribers_with_insight_access
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.cdp.backend.internal_events import LEGACY_INSIGHT_ALERT_EVENT


class TestInsightAlertEmailDestination(APIBaseTest):
    def _alert(self) -> AlertConfiguration:
        return create_insight_alert(self.team)

    @parameterized.expand([("insight_kept", False, True), ("insight_deleted", True, False)])
    def test_a_destination_row_reaches_only_users_who_can_still_see_the_insight(
        self, _name: str, insight_deleted: bool, user_reached: bool
    ) -> None:
        alert = self._alert()
        denied = User.objects.create_and_join(self.organization, "denied@example.com", None)
        with team_scope(self.team.id):
            configuration = platform_testing.create_configuration(
                team_id=self.team.id,
                name="alert",
                source_kind=SourceKind.INSIGHT,
                check_interval_minutes=60,
                source_config={"insight_id": alert.insight.id},
            )
        if insight_deleted:
            alert.insight.deleted = True
            alert.insight.save()

        def can_view(access_control: UserAccessControl, *_args: object) -> bool:
            return access_control._user.id != denied.id

        with patch.object(UserAccessControl, "check_access_level_for_object", autospec=True, side_effect=can_view):
            reached = subscribers_with_insight_access(
                team_id=self.team.id, configuration_id=configuration.id, user_ids=[self.user.id, denied.id]
            )

        assert reached == ([self.user.id] if user_reached else [])

    @parameterized.expand(
        [
            ("can see the insight", "row", True),
            ("denied the insight", "row", False),
            ("can see the insight of an alert with no row", "native", True),
            ("denied the insight of an alert with no row", "native", False),
            ("no alert", None, True),
        ]
    )
    def test_the_platform_sees_an_alert_and_its_creator_only_when_its_insight_is_visible(
        self, _name: str, kept_as: str | None, can_see_insight: bool
    ) -> None:
        if kept_as == "row":
            alert_id = create_insight_alert(self.team, created_by=self.user).id
        elif kept_as == "native":
            with team_scope(self.team.id):
                alert_id = platform_testing.create_configuration(
                    team_id=self.team.id,
                    name="alert",
                    source_kind=SourceKind.INSIGHT,
                    check_interval_minutes=60,
                    source_config={"insight_id": self._alert().insight.id},
                    created_by_id=self.user.id,
                ).id
        else:
            alert_id = uuid4()

        with patch.object(UserAccessControl, "check_access_level_for_object", return_value=can_see_insight):
            visible = insight_alert_viewer(team_id=self.team.id, alert_id=alert_id, user_id=self.user.id)

        assert visible is (can_see_insight and kept_as is not None)
        expected_creator = self.user.id if kept_as is not None else None
        assert insight_alert_creator(team_id=self.team.id, alert_id=alert_id) == expected_creator

    @parameterized.expand([("firing", LEGACY_INSIGHT_ALERT_EVENT), ("errored", INSIGHT_ALERT_ERRORED_EVENT_ID)])
    def test_subscriptions_reach_no_one_without_subscriber_destinations(self, _name: str, event_id: str) -> None:
        alert = self._alert()
        AlertSubscription.objects.create(user=self.user, alert_configuration=alert)

        groups = list_delivery_destination_groups(
            team_id=self.team.id, alert_id=str(alert.id), allowed_event_ids=[event_id]
        )

        assert groups == []
