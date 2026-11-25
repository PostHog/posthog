from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any
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


# Each spec with the row event kind it serves: an incident manager opens on a firing and closes on a resolve.
SPECS = (
    (_spec("$logs_alert_firing"), AlertEventKind.FIRING),
    (_spec("$logs_alert_resolved"), AlertEventKind.RESOLVED),
    (_spec("$logs_alert_incident_opened", IncidentAction.TRIGGER), AlertEventKind.FIRING),
    (_spec("$logs_alert_incident_closed", IncidentAction.RESOLVE), AlertEventKind.RESOLVED),
)
EVENT_IDS = tuple(spec.event_id for spec, _kind in SPECS)
FIRING_AND_RESOLVED = (AlertEventKind.FIRING, AlertEventKind.RESOLVED)
TYPES = (
    DestinationType.SLACK,
    DestinationType.WEBHOOK,
    DestinationType.DISCORD,
    DestinationType.TEAMS,
    DestinationType.PAGERDUTY,
)


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
                "inputs_schema": [
                    {"key": "url", "type": "string"},
                    {"key": "body", "type": "json"},
                    {"key": "headers", "type": "dictionary"},
                    {"key": "method", "type": "choice"},
                    {"key": "secret_headers", "type": "dictionary", "secret": True},
                    {"key": "signing_secret", "type": "string", "secret": True},
                ],
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

    def _configs(
        self, data: AlertDestinationData, event_kinds: Collection[AlertEventKind] = FIRING_AND_RESOLVED
    ) -> list[AlertDestinationConfig]:
        return [
            build_alert_destination_config(
                spec=spec, alert_id=str(self.alert_id), alert_name="API errors", data=data, slack_context_elements=()
            )
            for spec, kind in SPECS
            if kind in event_kinds and destination_handles_event_kind(DestinationType(data["type"]), spec)
        ]

    def _hog_functions(self, destination_type: DestinationType) -> tuple[UUID, ...]:
        return create_alert_destination_hog_functions(
            self._configs(self.data[destination_type]),
            team_id=self.team.id,
            created_by_id=self.user.id,
            alert_id=str(self.alert_id),
            allowed_event_ids=EVENT_IDS,
        )

    def _row(
        self,
        destination_type: DestinationType,
        copies: tuple[UUID, ...] = (),
        event_kinds: tuple[AlertEventKind, ...] = FIRING_AND_RESOLVED,
    ) -> UUID:
        row = record_source_destination(
            team_id=self.team.id,
            public_id=self.alert_id,
            data=self.data[destination_type],
            event_kinds=event_kinds,
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
            row_event_kinds=lambda _type: FIRING_AND_RESOLVED,
        )

    @parameterized.expand([(destination_type.value, destination_type) for destination_type in TYPES])
    def test_customize_then_reset_keeps_one_sender_for_every_stock_type(
        self, _name: str, destination_type: DestinationType
    ) -> None:
        row_id = self._row(destination_type)
        assert self._senders() == [f"row:{destination_type}"]

        customized = self._customize(destination_id=row_id)

        assert customized.created is True
        assert len(customized.hog_function_ids) == 2
        assert self._senders() == [f"hog_functions:{destination_type}"]
        assert [
            row.id for row in list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id)
        ] == [row_id]
        (group,) = self._groups()
        assert group.data == {
            key: value for key, value in self.data[destination_type].items() if key != "slack_channel_name"
        } | {"type": destination_type}

        reset = self._reset(customized.hog_function_ids)

        assert self._senders() == [f"row:{destination_type}"]
        (row,) = list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id)
        assert (row.id, reset.destination_id, row.legacy_hog_function_ids) == (row_id, row_id, ())
        assert not HogFunction.objects.filter(id__in=customized.hog_function_ids, deleted=False).exists()

    def test_customize_keeps_the_hog_functions_a_row_copies_and_writes_none(self) -> None:
        hog_function_ids = self._hog_functions(DestinationType.SLACK)
        row_id = self._row(DestinationType.SLACK, copies=hog_function_ids)
        assert self._senders() == ["hog_functions:slack"]

        customized = self._customize(destination_id=row_id)

        assert (customized.created, set(customized.hog_function_ids)) == (False, set(hog_function_ids))
        assert self._senders() == ["hog_functions:slack"]
        (row,) = list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id)
        assert (row.id, set(row.legacy_hog_function_ids)) == (row_id, set(hog_function_ids))
        assert HogFunction.objects.filter(team=self.team, deleted=False).count() == len(hog_function_ids)

    def test_customize_keeps_the_rows_event_kinds_and_its_credentials_encrypted(self) -> None:
        self.data[DestinationType.WEBHOOK]["webhook_headers"] = {"Authorization": "Bearer test-token"}
        row_id = self._row(DestinationType.WEBHOOK, event_kinds=(AlertEventKind.FIRING,))

        (hog_function_id,) = self._customize(destination_id=row_id).hog_function_ids

        hog_function = HogFunction.objects.get(id=hog_function_id)
        filters, inputs, encrypted = (
            hog_function.filters or {},
            hog_function.inputs or {},
            hog_function.encrypted_inputs or {},
        )
        assert filters["events"][0]["id"] == "$logs_alert_firing"
        assert "url" not in inputs and "secret_headers" not in inputs
        assert encrypted["url"]["value"] == "https://example.com/hook"
        assert encrypted["secret_headers"]["value"] == {"Authorization": "Bearer test-token"}

        self._reset([hog_function_id])

        (row,) = list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id)
        assert row.data["webhook_headers"] == {"Authorization": "Bearer test-token"}

    @parameterized.expand(
        [
            ("signs_its_requests", None, None, {"signing_secret": {"value": "whsec_test"}}),
            ("templated_url", {"url": "https://example.com/hooks/{event.properties.alert_id}"}, None, None),
            ("templated_header", {"headers": {"X-Alert-ID": "{event.properties.alert_id}"}}, None, None),
            ("put_method", {"method": "PUT"}, None, None),
            (
                "different_secret_headers_per_event",
                None,
                {"secret_headers": {"value": {"Authorization": "Bearer second-token"}}},
                {"secret_headers": {"value": {"Authorization": "Bearer first-token"}}},
            ),
        ]
    )
    def test_reset_is_refused_when_the_standard_message_cannot_send_the_same_way(
        self,
        _name: str,
        input_values: dict[str, Any] | None,
        last_encrypted: dict[str, Any] | None,
        encrypted: dict[str, Any] | None,
    ) -> None:
        hog_function_ids = self._hog_functions(DestinationType.WEBHOOK)
        hog_functions = list(HogFunction.objects.filter(id__in=hog_function_ids).order_by("id"))
        for index, hog_function in enumerate(hog_functions):
            if input_values is not None:
                hog_function.inputs = {
                    **(hog_function.inputs or {}),
                    **{key: {"value": value} for key, value in input_values.items()},
                }
            chosen = last_encrypted if last_encrypted is not None and index == len(hog_functions) - 1 else encrypted
            if chosen is not None:
                hog_function.encrypted_inputs = chosen
            hog_function.save(update_fields=["inputs", "encrypted_inputs"])

        with self.assertRaises(AlertDestinationValidationError):
            self._reset(hog_function_ids)

    def test_reset_is_refused_for_a_hog_function_that_never_receives_the_alert(self) -> None:
        hog_function_ids = self._hog_functions(DestinationType.WEBHOOK)
        planted = HogFunction.objects.get(id=hog_function_ids[0])
        planted.filters = {key: value for key, value in (planted.filters or {}).items() if key != "source"}
        planted.save(update_fields=["filters"])

        with self.assertRaises(AlertDestinationValidationError):
            self._reset(hog_function_ids)
        assert HogFunction.objects.filter(id__in=hog_function_ids, deleted=False).count() == 2

        assert self._senders() == ["hog_functions:webhook"]

    def test_reset_sends_a_secret_header_over_an_added_one_of_the_same_name(self) -> None:
        hog_function_ids = self._hog_functions(DestinationType.WEBHOOK)
        for hog_function in HogFunction.objects.filter(id__in=hog_function_ids):
            hog_function.inputs = {**(hog_function.inputs or {}), "headers": {"value": {"authorization": "old"}}}
            hog_function.encrypted_inputs = {"secret_headers": {"value": {"Authorization": "new"}}}
            hog_function.save(update_fields=["inputs", "encrypted_inputs"])

        self._reset(hog_function_ids)

        (row,) = list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id)
        assert row.data["webhook_headers"] == {"Authorization": "new"}

    def test_a_pagerduty_destination_does_not_move_while_its_alert_fires(self) -> None:
        row_id = self._row(DestinationType.PAGERDUTY)
        with team_scope(self.team.id):
            platform_testing.start_firing(
                self.configuration.id, team_id=self.team.id, at=datetime(2026, 1, 1, tzinfo=UTC)
            )

        with self.assertRaises(AlertDestinationValidationError):
            self._customize(destination_id=row_id)

        assert self._senders() == ["row:pagerduty"]

    def test_reset_is_refused_while_some_of_the_destinations_events_are_paused(self) -> None:
        hog_function_ids = self._hog_functions(DestinationType.SLACK)
        HogFunction.objects.filter(id=hog_function_ids[0]).update(enabled=False)

        with self.assertRaises(AlertDestinationValidationError):
            self._reset(hog_function_ids)

        assert self._senders() == ["hog_functions:slack"]

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

    def test_a_second_customize_of_the_same_row_writes_no_more_hog_functions(self) -> None:
        row_id = self._row(DestinationType.SLACK)
        first = self._customize(destination_id=row_id)

        second = self._customize(destination_id=row_id)

        assert (second.created, set(second.hog_function_ids)) == (False, set(first.hog_function_ids))
        assert HogFunction.objects.filter(team=self.team, deleted=False).count() == len(first.hog_function_ids)
        assert self._senders() == ["hog_functions:slack"]

    def test_the_reset_row_outlives_a_later_delete_of_the_retired_hog_functions(self) -> None:
        hog_function_ids = self._hog_functions(DestinationType.WEBHOOK)
        row_id = self._row(DestinationType.WEBHOOK, copies=hog_function_ids)

        reset = self._reset(hog_function_ids)
        # A delete through the generic HogFunction API saves the function, which runs the receiver that
        # deletes every row copying it.
        for hog_function in HogFunction.objects.filter(id__in=hog_function_ids):
            hog_function.deleted = True
            hog_function.save(update_fields=["deleted"])

        (row,) = list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id)
        assert row.id == reset.destination_id == row_id
        assert self._senders() == ["row:webhook"]

    def test_reset_is_refused_and_changes_nothing_while_the_source_evaluates_the_alert(self) -> None:
        self._configure(PlatformAlertOwner.SOURCE)
        hog_function_ids = self._hog_functions(DestinationType.SLACK)

        with self.assertRaises(AlertDestinationValidationError):
            self._reset(hog_function_ids)

        assert self._senders() == ["hog_functions:slack"]
