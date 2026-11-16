from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership
from posthog.models.organization_notification_lock import OrganizationMemberNotificationLock
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.alerts_platform.backend.delivery import refusal_notices
from products.alerts_platform.backend.delivery.refusal_notices import notify_refused
from products.alerts_platform.backend.delivery.transport import DestinationRefused
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.logic import source_access
from products.alerts_platform.backend.models import PlatformAlertConfiguration
from products.alerts_platform.backend.tests.delivery_messages import alert_message
from products.logs.backend.models import LogsAlertConfiguration
from products.notifications.backend.facade.testing import stored_notifications_for_team

NOW = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
REFUSAL = DestinationRefused("The webhook destination refused the message with status 400.")


class TestRefusalNotices(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
        flag.start()
        self.addCleanup(flag.stop)
        email_available = patch.object(refusal_notices, "is_email_available", return_value=True)
        email_available.start()
        self.addCleanup(email_available.stop)
        email_message = patch.object(refusal_notices, "EmailMessage")
        self.email = email_message.start()
        self.addCleanup(email_message.stop)
        self.teammate = User.objects.create_and_join(self.organization, "teammate@example.com", None)
        self.legacy_alert_id = UUID("01a1bb95-3742-7730-8e4d-d610fd77daee")
        with team_scope(self.team.id):
            self.configuration = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="API errors",
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config={},
                check_interval_minutes=10,
                legacy_configuration_id=self.legacy_alert_id,
            )

    def _notify(
        self,
        creator: User | None,
        *,
        destination: str = "destination-1",
        now: datetime = NOW,
        can_view: bool = True,
    ) -> list[UUID]:
        looked_up: list[UUID] = []

        def creator_of(*, team_id: int, alert_id: UUID) -> int | None:
            looked_up.append(alert_id)
            return creator.id if creator is not None else None

        def viewer_of(*, team_id: int, alert_id: UUID, user_id: int) -> bool:
            return can_view and alert_id == self.legacy_alert_id

        message = replace(
            alert_message(),
            configuration_id=str(self.configuration.id),
            alert_url="https://app.example.com/project/1/insights/abc123/alerts?alert_id=a1",
        )
        with (
            patch.dict(refusal_notices._creators, {SourceKind.LOGS: creator_of}),
            patch.dict(source_access._viewers, {SourceKind.LOGS: viewer_of}),
        ):
            notify_refused(team_id=self.team.id, message=message, destination=destination, refusal=REFUSAL, now=now)
        return looked_up

    def _recipients(self) -> list[list[int]]:
        return [sorted(event.resolved_user_ids) for event in stored_notifications_for_team(self.team.id)]

    def test_the_creator_is_told_once_a_day_per_destination(self) -> None:
        # The source finds its creator by the alert's public id, its own row's id.
        assert self._notify(self.user) == [self.legacy_alert_id]
        assert self._notify(self.user) == []
        self._notify(self.user, destination="destination-1-repointed")
        self._notify(self.user, now=NOW + timedelta(days=1))

        assert self._recipients() == [[self.user.id]] * 3
        event = stored_notifications_for_team(self.team.id)[0]
        # The inbox groups by resource, so each alert keeps its own group.
        assert event.resource_id == str(self.configuration.id)
        assert (event.notification_type, event.body, event.source_url) == (
            "alert_destination_refused",
            "The webhook destination refused the message with status 400. "
            "Every notification sent there will fail until the destination is fixed.",
            # The query selects the alert on the insight's alerts page.
            "/project/1/insights/abc123/alerts?alert_id=a1",
        )
        # `posthog.email` sends one campaign key to a recipient once, so a key per notice is one email per notice.
        assert len({kwargs["campaign_key"] for _, kwargs in self.email.call_args_list}) == 3
        assert {call.args[0] for call in self.email.return_value.add_user_recipient.call_args_list} == {self.user}

    @parameterized.expand(
        [
            ("left the organization", "former", True),
            ("no recorded creator", None, True),
            ("lost access to the alert", "member", False),
        ]
    )
    def test_nobody_is_told_when_the_creator_cannot_be_reached(
        self, _name: str, creator_kind: str | None, can_view: bool
    ) -> None:
        creator = None
        if creator_kind == "former":
            creator = User.objects.create_and_join(self.organization, "former@example.com", None)
            creator.leave(organization=self.organization)
        elif creator_kind == "member":
            creator = self.user

        self._notify(creator, can_view=can_view)

        assert self._recipients() == []
        self.email.assert_not_called()

    @parameterized.expand([("turned off by the creator", False), ("kept on by the organization", True)])
    def test_the_email_follows_the_data_pipeline_errors_setting(
        self, _name: str, organization_keeps_it_on: bool
    ) -> None:
        self.user.partial_notification_settings = {"plugin_disabled": False}
        self.user.save()
        if organization_keeps_it_on:
            OrganizationMemberNotificationLock.objects.create(
                organization=self.organization,
                organization_membership=OrganizationMembership.objects.get(user=self.user),
                setting="plugin_disabled",
                locked_value=True,
            )

        self._notify(self.user)

        assert self._recipients() == [[self.user.id]]
        assert self.email.called is organization_keeps_it_on

    def test_a_notice_that_fails_never_raises_and_is_tried_again_on_the_next_refusal(self) -> None:
        with patch.object(refusal_notices.cache, "get", side_effect=ConnectionError("cache down")):
            self._notify(self.user)
        with patch.object(refusal_notices, "create_notification", side_effect=RuntimeError("notifications down")):
            self._notify(self.user)
        # The email does not wait on the in-app notification.
        assert self.email.call_count == 1
        self._notify(self.user)

        assert self._recipients() == [[self.user.id]]

    def test_a_converted_logs_alert_tells_the_creator_of_its_logs_alert(self) -> None:
        logs_alert = LogsAlertConfiguration.objects.create(
            team=self.team, name="API errors", enabled=False, created_by=self.teammate
        )
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                legacy_configuration_id=logs_alert.id
            )

        message = replace(alert_message(), configuration_id=str(self.configuration.id))
        notify_refused(team_id=self.team.id, message=message, destination="destination-1", refusal=REFUSAL, now=NOW)

        assert self._recipients() == [[self.teammate.id]]
