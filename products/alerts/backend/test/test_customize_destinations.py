from collections.abc import Collection
from uuid import UUID, uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.alerts.backend.facade.destinations import (
    build_alert_destination_config,
    create_alert_destination_hog_functions,
    customize_source_destination,
    destination_handles_event_kind,
    list_alert_destination_groups,
    reset_source_destination,
)
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import (
    create_alert_destinations,
    list_alert_destinations,
    record_source_destination,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationConfig,
    AlertDestinationData,
    AlertDestinationValidationError,
    AlertEventKind,
    DestinationType,
    EventKindSpec,
    IncidentAction,
    NewAlertDestination,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.cdp.backend.facade.models import HogFunction, HogFunctionTemplate
from products.cdp.backend.templates.discord.template_discord import template as template_discord
from products.cdp.backend.templates.fixtures import template_pagerduty, template_slack
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.cdp.backend.templates.microsoft_teams.template_microsoft_teams import template as template_microsoft_teams


def _spec(event_id: str, incident_action: IncidentAction | None = None) -> EventKindSpec:
    return EventKindSpec(
        event_id=event_id,
        display_kind=event_id,
        header=f"Alert {event_id}",
        details=(("Event", event_id),),
        primary_action_url="https://example.com/alert",
        primary_action_label="View alert",
        webhook_body={"event": event_id},
        incident_action=incident_action,
    )


SPECS = (
    _spec("$logs_alert_firing"),
    _spec("$logs_alert_resolved"),
    _spec("$logs_alert_incident_opened", IncidentAction.TRIGGER),
    _spec("$logs_alert_incident_closed", IncidentAction.RESOLVE),
)
EVENT_IDS = tuple(spec.event_id for spec in SPECS)
TYPES = (
    DestinationType.SLACK,
    DestinationType.WEBHOOK,
    DestinationType.DISCORD,
    DestinationType.TEAMS,
    DestinationType.PAGERDUTY,
)
# One HogFunction per message kind, and an incident manager gets the opened and closed pair.
HOG_FUNCTION_COUNTS = {DestinationType.PAGERDUTY: 2}


class TestCustomizeSourceDestination(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        for template in (template_slack, template_pagerduty, template_discord, template_microsoft_teams):
            sync_template_to_db(template)
        HogFunctionTemplate.objects.get_or_create(
            template_id="template-webhook",
            defaults={
                "sha": "1.0.0",
                "name": "Webhook",
                "code": "return event",
                "code_language": "hog",
                "inputs_schema": [{"key": "url", "type": "string"}, {"key": "body", "type": "json"}],
                "type": "destination",
                "status": "stable",
                "free": True,
            },
        )
        slack = Integration.objects.create(team=self.team, kind="slack", config={}, sensitive_config={})
        self.data: dict[DestinationType, AlertDestinationData] = {
            DestinationType.SLACK: {
                "type": DestinationType.SLACK,
                "slack_workspace_id": slack.id,
                "slack_channel_id": "C0123456789",
                "slack_channel_name": "alerts",
            },
            DestinationType.WEBHOOK: {"type": DestinationType.WEBHOOK, "webhook_url": "https://example.com/hook"},
            DestinationType.DISCORD: {
                "type": DestinationType.DISCORD,
                "webhook_url": "https://discord.com/api/webhooks/1/secret",
            },
            DestinationType.TEAMS: {
                "type": DestinationType.TEAMS,
                "webhook_url": "https://prod-01.westus.logic.azure.com/workflows/abc/triggers/manual/paths/invoke",
            },
            DestinationType.PAGERDUTY: {
                "type": DestinationType.PAGERDUTY,
                "pagerduty_routing_key": "0123456789abcdef0123456789abcdef",
                "pagerduty_severity": "critical",
                "pagerduty_region": "us",
            },
        }
        self._configure(PlatformAlertOwner.PLATFORM)

    def _configure(self, owner: PlatformAlertOwner) -> None:
        self.alert_id = uuid4()
        with team_scope(self.team.id):
            self.configuration = platform_testing.create_configuration(
                team=self.team,
                name="API errors",
                source_kind=SourceKind.LOGS,
                check_interval_minutes=5,
                owner=owner,
                legacy_configuration_id=self.alert_id,
            )

    def _configs(self, data: AlertDestinationData) -> list[AlertDestinationConfig]:
        return [
            build_alert_destination_config(
                spec=spec, alert_id=str(self.alert_id), alert_name="API errors", data=data, slack_context_elements=()
            )
            for spec in SPECS
            if destination_handles_event_kind(DestinationType(data["type"]), spec)
        ]

    def _hog_functions(self, destination_type: DestinationType) -> tuple[UUID, ...]:
        return create_alert_destination_hog_functions(
            self._configs(self.data[destination_type]),
            team_id=self.team.id,
            created_by_id=self.user.id,
            alert_id=str(self.alert_id),
            allowed_event_ids=EVENT_IDS,
        )

    def _row(self, destination_type: DestinationType, copies: tuple[UUID, ...] = ()) -> UUID:
        row = record_source_destination(
            team_id=self.team.id,
            public_id=self.alert_id,
            data=self.data[destination_type],
            event_kinds=(AlertEventKind.FIRING,),
            hog_function_ids=copies,
            hog_function_groups=self._groups(),
        )
        assert row is not None
        return row.id

    def _groups(self):
        return list_alert_destination_groups(
            team_id=self.team.id, alert_id=str(self.alert_id), allowed_event_ids=EVENT_IDS
        )

    def _senders(self) -> list[str]:
        """What delivery sends from, one entry per sender: a row is skipped while a HogFunction it copies exists."""
        groups = self._groups()
        live = {hog_function_id for group in groups for hog_function_id in group.hog_function_ids}
        rows = [
            row
            for row in list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id)
            if row.enabled and live.isdisjoint(row.legacy_hog_function_ids)
        ]
        return sorted(
            [f"hog_functions:{group.data['type']}" for group in groups] + [f"row:{row.data['type']}" for row in rows]
        )

    def _customize(self, *, destination_id: UUID | None = None, hog_function_ids: Collection[UUID] = ()):
        return customize_source_destination(
            team_id=self.team.id,
            alert_id=self.alert_id,
            allowed_event_ids=EVENT_IDS,
            allowed_destination_types=TYPES,
            destination_id=destination_id,
            hog_function_ids=hog_function_ids,
            build_configs=self._configs,
            created_by_id=self.user.id,
        )

    def _reset(self, hog_function_ids: Collection[UUID]):
        return reset_source_destination(
            team_id=self.team.id,
            alert_id=self.alert_id,
            allowed_event_ids=EVENT_IDS,
            allowed_destination_types=TYPES,
            hog_function_ids=hog_function_ids,
            row_event_kinds=lambda _type: (AlertEventKind.FIRING,),
        )

    @parameterized.expand([(destination_type.value, destination_type) for destination_type in TYPES])
    def test_customize_then_reset_keeps_one_sender_for_every_stock_type(
        self, _name: str, destination_type: DestinationType
    ) -> None:
        row_id = self._row(destination_type)
        assert self._senders() == [f"row:{destination_type}"]

        customized = self._customize(destination_id=row_id)

        assert customized.created is True
        assert len(customized.hog_function_ids) == HOG_FUNCTION_COUNTS.get(destination_type, 2)
        assert self._senders() == [f"hog_functions:{destination_type}"]
        (group,) = self._groups()
        assert group.data == {
            key: value for key, value in self.data[destination_type].items() if key != "slack_channel_name"
        } | {"type": destination_type}

        reset = self._reset(customized.hog_function_ids)

        assert self._senders() == [f"row:{destination_type}"]
        (row,) = list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id)
        assert row.id == reset.destination_id and row.legacy_hog_function_ids == ()
        assert not HogFunction.objects.filter(id__in=customized.hog_function_ids, deleted=False).exists()

    def test_customize_keeps_the_hog_functions_a_row_copies_and_writes_none(self) -> None:
        hog_function_ids = self._hog_functions(DestinationType.SLACK)
        row_id = self._row(DestinationType.SLACK, copies=hog_function_ids)
        assert self._senders() == ["hog_functions:slack"]

        customized = self._customize(destination_id=row_id)

        assert (customized.created, set(customized.hog_function_ids)) == (False, set(hog_function_ids))
        assert self._senders() == ["hog_functions:slack"]
        assert list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id) == ()
        assert HogFunction.objects.filter(team=self.team, deleted=False).count() == len(hog_function_ids)

    def test_customize_of_a_paused_row_writes_paused_hog_functions(self) -> None:
        (paused,) = create_alert_destinations(
            team_id=self.team.id,
            configuration_id=self.configuration.id,
            destinations=[
                NewAlertDestination(
                    data=self.data[DestinationType.WEBHOOK], event_kinds=(AlertEventKind.FIRING,), enabled=False
                )
            ],
        )
        row_id = paused.id

        customized = self._customize(destination_id=row_id)

        assert set(
            HogFunction.objects.filter(id__in=customized.hog_function_ids).values_list("enabled", flat=True)
        ) == {False}

    def test_a_second_customize_of_the_same_row_is_refused(self) -> None:
        row_id = self._row(DestinationType.SLACK)
        self._customize(destination_id=row_id)

        with self.assertRaises(AlertDestinationValidationError):
            self._customize(destination_id=row_id)

        assert self._senders() == ["hog_functions:slack"]

    def test_the_reset_row_outlives_a_later_delete_of_the_retired_hog_functions(self) -> None:
        hog_function_ids = self._hog_functions(DestinationType.WEBHOOK)
        self._row(DestinationType.WEBHOOK, copies=hog_function_ids)

        reset = self._reset(hog_function_ids)
        # A delete through the generic HogFunction API saves the function, which runs the receiver that
        # deletes every row copying it.
        for hog_function in HogFunction.objects.filter(id__in=hog_function_ids):
            hog_function.deleted = True
            hog_function.save(update_fields=["deleted"])

        (row,) = list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id)
        assert row.id == reset.destination_id
        assert self._senders() == ["row:webhook"]

    def test_reset_is_refused_and_changes_nothing_while_the_source_evaluates_the_alert(self) -> None:
        self._configure(PlatformAlertOwner.SOURCE)
        hog_function_ids = self._hog_functions(DestinationType.SLACK)

        with self.assertRaises(AlertDestinationValidationError):
            self._reset(hog_function_ids)

        assert self._senders() == ["hog_functions:slack"]
