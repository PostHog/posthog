from datetime import UTC, datetime, timedelta
from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.schema_enums import AlertCalculationInterval, AlertState

from products.alerts.backend.facade.contracts import INSIGHT_ALERT_DESTINATION_EVENT_IDS
from products.alerts.backend.facade.destinations import (
    build_insight_alert_destination_configs,
    list_alert_destination_groups,
)
from products.alerts.backend.insight_alert_state_machine import FIRING_NOT_RENOTIFIED_KEY
from products.alerts.backend.logic.destination_configs import destination_filter
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, AlertSubscription, InvestigationStatus
from products.alerts.backend.platform_cutover import CutoverSkip, RollbackSkip, cut_over_team, roll_back_team
from products.alerts.backend.platform_subscribers import sync_subscriber_destinations
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import list_source_destinations, record_source_destination
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    DeliveryPath,
    DestinationType,
)
from products.cdp.backend.facade.models import HogFunction
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.templates.discord.template_discord import template as template_discord
from products.cdp.backend.templates.fixtures import template_pagerduty, template_slack
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.cdp.backend.templates.microsoft_teams.template_microsoft_teams import template as template_microsoft_teams

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
_CUTOVER = "products.alerts.backend.platform_cutover"


def sync_destination_templates() -> None:
    sync_template_to_db(template_slack)
    sync_template_to_db(template_microsoft_teams)
    sync_template_to_db(template_pagerduty)
    sync_template_to_db(template_discord)
    HogFunctionTemplate.objects.get_or_create(
        template_id="template-webhook",
        defaults={
            "sha": "1.0.0",
            "name": "Webhook",
            "description": "Generic webhook template",
            "code": "return event",
            "code_language": "hog",
            "inputs_schema": [
                {"key": "url", "type": "string"},
                {"key": "body", "type": "json"},
                {"key": "headers", "type": "dictionary"},
                {"key": "secret_headers", "type": "dictionary", "secret": True},
            ],
            "type": "destination",
            "status": "stable",
        },
    )


class TestInsightPlatformCutover(APIBaseTest):
    def _alert(self, **overrides: Any) -> AlertConfiguration:
        return create_insight_alert(
            self.team,
            **{"next_check_at": NOW + timedelta(minutes=3), "last_notified_at": NOW - timedelta(days=1), **overrides},
        )

    @parameterized.expand(
        [
            ("quiet", {}, "not_firing"),
            ("firing", {"state": AlertState.FIRING}, "firing"),
            ("errored", {"state": AlertState.ERRORED}, "errored"),
            (
                "snoozed_keeps_checking_muted",
                {"state": AlertState.SNOOZED, "snoozed_until": NOW + timedelta(hours=1)},
                "not_firing",
            ),
            ("disabled", {"enabled": False, "next_check_at": None}, "not_firing"),
            ("statistical_detector", {"detector_config": {"type": "zscore"}}, "not_firing"),
            ("ai_detector", {"detector_config": {"type": "llm"}}, "not_firing"),
            ("real_time", {"calculation_interval": AlertCalculationInterval.REAL_TIME.value}, "not_firing"),
            (
                "investigated",
                {"detector_config": {"type": "zscore"}, "investigation_agent_enabled": True},
                "not_firing",
            ),
        ]
    )
    def test_an_alert_moves_with_its_state_and_schedule(
        self, _name: str, overrides: dict[str, Any], platform_state: str
    ) -> None:
        alert = self._alert(**overrides)

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped is None
        alert.refresh_from_db()
        assert (alert.owner, alert.owner_changed_at) == ("platform", NOW)
        with team_scope(self.team.id):
            copy = platform_testing.copy_of(alert.id)
            instance = platform_testing.alert_for(copy.id)
        assert (copy.owner, copy.next_check_at) == (
            "platform",
            max(alert.next_check_at or NOW, NOW + timedelta(minutes=1)),
        )
        assert instance is not None
        assert (instance.state, instance.last_notified_at) == (platform_state, alert.last_notified_at)

    @parameterized.expand(
        [
            ("check_due", {"next_check_at": NOW}, CutoverSkip.CHECK_DUE),
            ("never_scheduled", {"next_check_at": None}, CutoverSkip.CHECK_DUE),
        ]
    )
    def test_an_alert_that_cannot_move_now_stays_with_insight(
        self, _name: str, overrides: dict[str, Any], reason: CutoverSkip
    ) -> None:
        alert = self._alert(**overrides)

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped == reason
        alert.refresh_from_db()
        assert alert.owner == "source"

    @parameterized.expand(
        [
            (
                "agent_running",
                InvestigationStatus.RUNNING,
                None,
                timedelta(minutes=10),
                CutoverSkip.INVESTIGATION_UNSETTLED,
            ),
            (
                "held_notification",
                InvestigationStatus.DONE,
                None,
                timedelta(minutes=10),
                CutoverSkip.INVESTIGATION_UNSETTLED,
            ),
            ("notification_sent", InvestigationStatus.DONE, NOW, timedelta(minutes=10), None),
            ("past_the_horizon", InvestigationStatus.RUNNING, None, timedelta(hours=2), None),
            ("firing_not_yet_notified", None, None, timedelta(minutes=5), CutoverSkip.NOTIFICATION_PENDING),
            ("firing_notified", None, NOW, timedelta(minutes=5), None),
            ("firing_past_its_workflow", None, None, timedelta(minutes=30), None),
            (
                "firing_not_renotified",
                None,
                None,
                timedelta(minutes=5),
                None,
                {FIRING_NOT_RENOTIFIED_KEY: True},
            ),
        ]
    )
    def test_an_alert_moves_only_once_its_last_firing_settles(
        self,
        _name: str,
        status: str | None,
        sent_at: datetime | None,
        age: timedelta,
        reason: CutoverSkip | None,
        triggered_metadata: dict | None = None,
    ) -> None:
        alert = self._alert(investigation_agent_enabled=True, detector_config={"type": "zscore"})
        alert.subscribed_users.add(self.user)
        check = AlertCheck.objects.create(
            alert_configuration=alert,
            state=AlertState.FIRING,
            investigation_status=status,
            notification_sent_at=sent_at,
            triggered_metadata=triggered_metadata,
        )
        AlertCheck.objects.filter(id=check.id).update(created_at=NOW - age)

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped == reason

    @parameterized.expand(
        [
            ("subscriber", CutoverSkip.NOTIFICATION_PENDING),
            ("custom_destination", CutoverSkip.NOTIFICATION_PENDING),
            ("team_wide_destination", CutoverSkip.NOTIFICATION_PENDING),
            ("nobody", None),
        ]
    )
    def test_a_firing_alert_waits_only_while_someone_can_be_notified(
        self, target: str, reason: CutoverSkip | None
    ) -> None:
        alert = self._alert()
        if target == "subscriber":
            alert.subscribed_users.add(self.user)
        elif target != "nobody":
            filters = destination_filter(str(alert.id), "$insight_alert_firing")
            if target == "team_wide_destination":
                filters["properties"] = []
            HogFunction.objects.create(
                team=self.team,
                name="Alert → webhook",
                type="internal_destination",
                hog="return 1",
                enabled=True,
                template_id="template-custom",
                filters=filters,
            )
        check = AlertCheck.objects.create(alert_configuration=alert, state=AlertState.FIRING)
        AlertCheck.objects.filter(id=check.id).update(created_at=NOW - timedelta(minutes=5))

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped == reason

    def test_an_alert_in_a_child_environment_stays_with_insight(self) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        alert = create_insight_alert(environment, next_check_at=NOW + timedelta(minutes=3))

        (result,) = cut_over_team(environment.id, now=NOW)

        assert result.skipped == CutoverSkip.ENVIRONMENT
        alert.refresh_from_db()
        assert alert.owner == "source"

    @parameterized.expand([("events_emitted", True, None), ("nothing_emits", False, CutoverSkip.NO_HOG_FUNCTION_PATH)])
    def test_an_alert_on_the_hog_function_path_moves_only_while_its_events_are_emitted(
        self, _name: str, emitter: bool, reason: CutoverSkip | None
    ) -> None:
        alert = self._alert()

        with (
            patch(f"{_CUTOVER}.choose_delivery_path", return_value=DeliveryPath.HOG_FUNCTION),
            patch(f"{_CUTOVER}.has_legacy_event_emitter", return_value=emitter),
        ):
            (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped == reason
        alert.refresh_from_db()
        assert alert.owner == ("source" if reason else "platform")

    def test_a_second_run_leaves_a_moved_alert_alone(self) -> None:
        self._alert()
        cut_over_team(self.team.id, now=NOW)

        (result,) = cut_over_team(self.team.id, now=NOW + timedelta(minutes=1))

        assert result.skipped == CutoverSkip.ALREADY_MOVED

    def _moved(self, **overrides: Any) -> AlertConfiguration:
        alert = self._alert(**overrides)
        cut_over_team(self.team.id, now=NOW)
        alert.refresh_from_db()
        return alert

    @parameterized.expand(
        [
            ("quiet", {}, None, False, AlertState.NOT_FIRING),
            ("errored", {"state": AlertState.ERRORED}, None, False, AlertState.ERRORED),
            # A snooze lives on the insight alert, so one set after the move survives the handback.
            ("snoozed_since", {}, NOW + timedelta(days=30), False, AlertState.SNOOZED),
            # The insight stack must not resume an alert the platform stopped.
            ("switched_off_by_the_platform", {"state": AlertState.ERRORED}, None, True, AlertState.ERRORED),
        ]
    )
    def test_rolling_back_after_the_shadow_carries_the_platform_state_back(
        self,
        _name: str,
        overrides: dict[str, Any],
        snoozed_until: datetime | None,
        switched_off: bool,
        state: AlertState,
    ) -> None:
        alert = self._moved(**overrides)
        if snoozed_until is not None:
            AlertConfiguration.objects.filter(id=alert.id).update(snoozed_until=snoozed_until)
        if switched_off:
            with team_scope(self.team.id):
                platform_testing.set_enabled(platform_testing.copy_of(alert.id).id, False)
        later = NOW + timedelta(days=8)
        with team_scope(self.team.id):
            platform_testing.set_due_at(platform_testing.copy_of(alert.id).id, later + timedelta(minutes=2))

        (result,) = roll_back_team(self.team.id, now=later)

        assert result.skipped is None
        alert.refresh_from_db()
        assert (alert.owner, alert.owner_changed_at, alert.state, alert.next_check_at, alert.enabled) == (
            "source",
            later,
            state,
            later + timedelta(minutes=2),
            not switched_off,
        )
        with team_scope(self.team.id):
            assert platform_testing.copy_of(alert.id).owner == "source"

    @parameterized.expand(
        [
            (DestinationType.SLACK, {"slack_workspace_id": 1, "slack_channel_id": "C-1"}),
            (DestinationType.WEBHOOK, {"webhook_url": "https://hooks.example.com/hook"}),
            (
                DestinationType.WEBHOOK,
                {"webhook_url": "https://hooks.example.com/hook", "webhook_headers": {"Authorization": "Bearer fake"}},
            ),
            (DestinationType.DISCORD, {"webhook_url": "https://discord.com/api/webhooks/1/secret"}),
            (
                DestinationType.TEAMS,
                {
                    "webhook_url": "https://prod-01.westus.logic.azure.com/workflows/1/triggers/manual/paths/invoke?sig=secret"
                },
            ),
            (DestinationType.PAGERDUTY, {"pagerduty_routing_key": "a" * 32}),
        ]
    )
    def test_rolling_back_gives_a_platform_only_destination_its_hog_functions(
        self, destination_type: DestinationType, fields: dict[str, Any]
    ) -> None:
        sync_destination_templates()
        alert = self._moved(created_by=self.user)
        AlertSubscription.objects.create(user=self.user, alert_configuration=alert, created_by=self.user)
        sync_subscriber_destinations(alert)
        data = cast(AlertDestinationData, {"type": destination_type, **fields})
        row = record_source_destination(
            team_id=self.team.id,
            public_id=alert.id,
            data=data,
            event_kinds=(AlertEventKind.FIRING,),
            hog_function_ids=(),
            hog_function_groups=[],
        )
        assert row is not None
        later = NOW + timedelta(days=8)
        with team_scope(self.team.id):
            platform_testing.set_due_at(platform_testing.copy_of(alert.id).id, later + timedelta(minutes=2))

        (result,) = roll_back_team(self.team.id, now=later)

        assert result.skipped is None
        groups = list_alert_destination_groups(
            team_id=self.team.id, alert_id=str(alert.id), allowed_event_ids=INSIGHT_ALERT_DESTINATION_EVENT_IDS
        )
        (group,) = [group for group in groups if group.hog_function_ids]
        shown = {key: value for key, value in data.items() if key != "webhook_headers"}
        assert {key: group.data.get(key) for key in shown} == shown
        rebuilt = HogFunction.objects.filter(id__in=group.hog_function_ids)
        if "webhook_headers" in data:
            (function,) = rebuilt
            assert (function.encrypted_inputs or {})["secret_headers"]["value"] == data["webhook_headers"]
            assert "secret_headers" not in (function.inputs or {})
        assert sorted(
            event["id"] for function in rebuilt for event in (function.filters or {}).get("events", [])
        ) == sorted(
            event["id"]
            for config in build_insight_alert_destination_configs(
                alert_id=str(alert.id), alert_name=alert.name, data=data
            )
            for event in config.payload["filters"]["events"]
        )
        (copy,) = [
            destination
            for destination in list_source_destinations(
                team_id=self.team.id, public_id=alert.id, hog_function_groups=groups
            )
            if destination.destination_id == row.id
        ]
        assert set(copy.hog_function_ids) == set(group.hog_function_ids)
        assert list(AlertSubscription.objects.filter(alert_configuration=alert).values_list("user_id", flat=True)) == [
            self.user.id
        ]

    @parameterized.expand(
        [
            ("never_moved", False, NOW + timedelta(days=8), RollbackSkip.NOT_MOVED),
            ("insight_check_due_during_shadow", True, NOW + timedelta(minutes=10), RollbackSkip.INSIGHT_CHECK_DUE),
        ]
    )
    def test_an_alert_that_cannot_move_back_now_stays(
        self, _name: str, moved: bool, at: datetime, reason: RollbackSkip
    ) -> None:
        alert = self._moved() if moved else self._alert()

        (result,) = roll_back_team(self.team.id, now=at)

        assert result.skipped == reason
        alert.refresh_from_db()
        assert alert.owner == ("platform" if moved else "source")
