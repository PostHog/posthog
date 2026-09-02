from typing import Any
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models.team.team import Team

from products.alerts.backend.destination_configs import (
    DESTINATION_SPECS,
    AlertDestinationConfig,
    AlertDestinationData,
    DestinationType,
    EventKindSpec,
    build_alert_destination_config,
)
from products.alerts.backend.destinations import (
    SPEC_BY_TEMPLATE_ID,
    AlertDelivery,
    AlertDestinationGroupKey,
    AlertDestinationRow,
    _raise_if_alert_already_has_these_destination_configs,
    alert_destination_group_key,
    alert_internal_event_delivered,
    group_alert_destination_rows,
    list_active_alert_destinations,
    serialize_deliveries,
    soft_delete_alert_destinations,
    soft_delete_all_alert_destinations,
)
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

ALLOWED_EVENT_IDS = (
    "$logs_alert_firing",
    "$logs_alert_resolved",
    "$logs_alert_errored",
    "$logs_alert_auto_disabled",
)

_DESTINATION_DATA: dict[DestinationType, AlertDestinationData] = {
    DestinationType.SLACK: {"type": DestinationType.SLACK, "slack_workspace_id": 1, "slack_channel_id": "C-ENG"},
    DestinationType.DISCORD: {"type": DestinationType.DISCORD, "webhook_url": "https://discord.example.com/hook"},
    DestinationType.WEBHOOK: {"type": DestinationType.WEBHOOK, "webhook_url": "https://example.com/hook"},
    DestinationType.TEAMS: {"type": DestinationType.TEAMS, "webhook_url": "https://teams.example.com/hook"},
}


def slack_inputs(channel_id: str, *, workspace_id: int = 1) -> dict[str, Any]:
    return {"slack_workspace": {"value": workspace_id}, "channel": {"value": channel_id}}


def webhook_inputs(url: str) -> dict[str, Any]:
    return {"url": {"value": url}}


_READABLE_INPUTS_BY_TEMPLATE: dict[str, dict[str, Any]] = {
    "template-slack": slack_inputs("C-ENG"),
    "template-webhook": webhook_inputs("https://example.com/hook"),
    "template-microsoft-teams": {"webhookUrl": {"value": "https://teams.example.com/hook"}},
}


def _schema_declaring_every_input(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": key, "type": "string"} for key in inputs]


class AlertDestinationTestCase(APIBaseTest):
    def _make_hog_function(
        self,
        *,
        template_id: str,
        alert_id: str,
        event_id: str = "$logs_alert_firing",
        inputs: dict[str, Any] | None = None,
        team: Team | None = None,
        name: str = "Test destination",
    ) -> HogFunction:
        resolved_inputs = _READABLE_INPUTS_BY_TEMPLATE.get(template_id, {}) if inputs is None else inputs
        return HogFunction.objects.create(
            team=team or self.team,
            name=name,
            type="destination",
            template_id=template_id,
            enabled=True,
            inputs_schema=_schema_declaring_every_input(resolved_inputs),
            inputs=resolved_inputs,
            hog="return event",
            filters={
                "events": [{"id": event_id, "type": "events"}],
                "properties": [{"key": "alert_id", "value": alert_id}],
            },
        )

    def _make_group(
        self,
        *,
        template_id: str,
        alert_id: str,
        inputs: dict[str, Any] | None = None,
        team: Team | None = None,
    ) -> list[HogFunction]:
        return [
            self._make_hog_function(
                template_id=template_id, alert_id=alert_id, event_id=event_id, inputs=inputs, team=team
            )
            for event_id in ALLOWED_EVENT_IDS
        ]

    def _assert_deleted(self, hog_functions: list[HogFunction]) -> None:
        for hog_function in hog_functions:
            hog_function.refresh_from_db()
            assert hog_function.deleted is True
            assert hog_function.enabled is False

    def _assert_intact(self, hog_functions: list[HogFunction]) -> None:
        for hog_function in hog_functions:
            hog_function.refresh_from_db()
            assert hog_function.deleted is False
            assert hog_function.enabled is True


def _config_for(destination_type: DestinationType, event_id: str) -> AlertDestinationConfig:
    return build_alert_destination_config(
        team=None,
        spec=EventKindSpec(
            event_id=event_id,
            display_kind=event_id,
            header=f"Logs alert {event_id}",
            details=(("Event", event_id),),
            primary_action_url="https://example.com/alert",
            primary_action_label="View alert",
            webhook_body={"event": event_id},
        ),
        alert_id="alert-1",
        alert_name="Signups",
        data=_DESTINATION_DATA[destination_type],
        slack_context_elements=(),
    )


def _group_key_of(config: AlertDestinationConfig) -> AlertDestinationGroupKey:
    return alert_destination_group_key(template_id=config.payload["template_id"], inputs=config.payload["inputs"])


class TestAlertDestinationGroupKey:
    @pytest.mark.parametrize("destination_type", list(DestinationType))
    def test_a_config_built_for_any_destination_type_is_readable(self, destination_type: DestinationType) -> None:
        assert _group_key_of(_config_for(destination_type, "$logs_alert_firing")).is_config_readable

    def test_every_event_kind_of_one_destination_shares_a_group_key(self) -> None:
        configs = [_config_for(DestinationType.SLACK, event_id) for event_id in ALLOWED_EVENT_IDS]

        assert len({_group_key_of(config) for config in configs}) == 1
        assert {config.payload["inputs"]["text"]["value"] for config in configs} == {
            f"Logs alert {event_id}" for event_id in ALLOWED_EVENT_IDS
        }

    def test_template_ids_and_destination_types_name_each_other_one_to_one(self) -> None:
        assert set(SPEC_BY_TEMPLATE_ID) == {spec.template_id for spec in DESTINATION_SPECS.values()}
        assert {spec.type for spec in SPEC_BY_TEMPLATE_ID.values()} == set(DestinationType)


class TestGroupAlertDestinationRows:
    def test_groups_two_configs_of_one_template_separately(self) -> None:
        eng, ops = uuid4(), uuid4()

        groups = group_alert_destination_rows(
            [
                AlertDestinationRow(eng, "template-slack", slack_inputs("C-ENG")),
                AlertDestinationRow(ops, "template-slack", slack_inputs("C-OPS")),
            ]
        )

        assert groups == {
            AlertDestinationGroupKey("template-slack", (("slack_channel_id", "C-ENG"), ("slack_workspace_id", 1))): {
                eng
            },
            AlertDestinationGroupKey("template-slack", (("slack_channel_id", "C-OPS"), ("slack_workspace_id", 1))): {
                ops
            },
        }

    def test_an_unreadable_row_collapses_its_whole_template_into_one_group(self) -> None:
        unreadable, readable, webhook = uuid4(), uuid4(), uuid4()

        groups = group_alert_destination_rows(
            [
                AlertDestinationRow(unreadable, "template-slack", {}),
                AlertDestinationRow(readable, "template-slack", slack_inputs("C-ENG")),
                AlertDestinationRow(webhook, "template-webhook", webhook_inputs("https://example.com/hook")),
            ]
        )

        assert groups == {
            AlertDestinationGroupKey("template-slack", None): {unreadable, readable},
            AlertDestinationGroupKey("template-webhook", (("webhook_url", "https://example.com/hook"),)): {webhook},
        }

    def test_groups_come_out_in_the_order_their_first_row_was_seen(self) -> None:
        ops, eng = uuid4(), uuid4()

        groups = group_alert_destination_rows(
            [
                AlertDestinationRow(ops, "template-slack", slack_inputs("C-OPS")),
                AlertDestinationRow(eng, "template-slack", slack_inputs("C-ENG")),
            ]
        )

        assert [key.config for key in groups] == [
            (("slack_channel_id", "C-OPS"), ("slack_workspace_id", 1)),
            (("slack_channel_id", "C-ENG"), ("slack_workspace_id", 1)),
        ]


class TestRaiseIfAlertAlreadyHasTheseDestinationConfigs(AlertDestinationTestCase):
    def _raise_if_exists(self, *, configs: list[tuple[str, dict[str, Any]]], alert_id: str = "alert-1") -> None:
        _raise_if_alert_already_has_these_destination_configs(
            team_id=self.team.id,
            alert_id=alert_id,
            allowed_event_ids=ALLOWED_EVENT_IDS,
            configs=[
                AlertDestinationConfig(team=self.team, payload={"template_id": template_id, "inputs": inputs})
                for template_id, inputs in configs
            ],
        )

    def test_rejects_a_destination_whose_config_already_exists(self) -> None:
        self._make_group(template_id="template-webhook", alert_id="alert-1", inputs=webhook_inputs("https://a"))

        with self.assertRaisesRegex(ValidationError, "already configured for this alert"):
            self._raise_if_exists(configs=[("template-webhook", webhook_inputs("https://a"))])

    def test_allows_a_second_destination_with_a_different_config(self) -> None:
        self._make_group(template_id="template-webhook", alert_id="alert-1", inputs=webhook_inputs("https://a"))

        self._raise_if_exists(configs=[("template-webhook", webhook_inputs("https://b"))])

    def test_allows_a_config_that_only_matches_another_alerts_destination(self) -> None:
        self._make_group(template_id="template-webhook", alert_id="alert-2", inputs=webhook_inputs("https://a"))

        self._raise_if_exists(configs=[("template-webhook", webhook_inputs("https://a"))])

    def test_allows_a_config_whose_only_match_is_deleted(self) -> None:
        destinations = self._make_group(
            template_id="template-webhook", alert_id="alert-1", inputs=webhook_inputs("https://a")
        )
        HogFunction.objects.filter(id__in=[destination.id for destination in destinations]).update(deleted=True)

        self._raise_if_exists(configs=[("template-webhook", webhook_inputs("https://a"))])

    def test_rejects_a_duplicate_of_a_disabled_destination(self) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1", inputs=slack_inputs("C-ENG"))
        HogFunction.objects.filter(id__in=[destination.id for destination in destinations]).update(enabled=False)

        with self.assertRaisesRegex(ValidationError, "already configured for this alert"):
            self._raise_if_exists(configs=[("template-slack", slack_inputs("C-ENG"))])

    def test_allows_a_destination_whose_config_cannot_be_read(self) -> None:
        self._make_group(template_id="template-slack", alert_id="alert-1", inputs={})

        self._raise_if_exists(configs=[("template-slack", {})])

    def test_rejects_a_duplicate_that_is_not_the_first_config_in_the_call(self) -> None:
        self._make_group(template_id="template-webhook", alert_id="alert-1", inputs=webhook_inputs("https://a"))

        with self.assertRaisesRegex(ValidationError, "already configured for this alert"):
            self._raise_if_exists(
                configs=[
                    ("template-slack", slack_inputs("C-NEW")),
                    ("template-webhook", webhook_inputs("https://a")),
                ]
            )

    def test_allows_a_config_that_matches_another_templates_destination(self) -> None:
        webhook_url = {"webhookUrl": {"value": "https://hooks.example.com/x"}}
        self._make_group(template_id="template-microsoft-teams", alert_id="alert-1", inputs=webhook_url)

        self._raise_if_exists(configs=[("template-discord", webhook_url)])


class TestSoftDeleteAlertDestinations(AlertDestinationTestCase):
    def test_deletes_alert_destination_with_matching_alert_id(self) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        soft_delete_alert_destinations(
            team_id=self.team.id,
            alert_id="alert-1",
            allowed_event_ids=ALLOWED_EVENT_IDS,
            hog_function_ids=[destination.id for destination in destinations],
        )

        self._assert_deleted(destinations)

    def test_rejects_partial_destination_group(self) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        with self.assertRaisesRegex(ValidationError, "Delete all destinations in this group"):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destinations[0].id],
            )

        self._assert_intact(destinations)

    @parameterized.expand(
        [
            ("slack_channels", "template-slack", slack_inputs("C-ENG"), slack_inputs("C-OPS")),
            (
                "webhook_urls",
                "template-webhook",
                webhook_inputs("https://example.com/a"),
                webhook_inputs("https://example.com/b"),
            ),
        ]
    )
    def test_deletes_one_of_two_destinations_of_the_same_type(
        self, _name: str, template_id: str, first_inputs: dict[str, Any], second_inputs: dict[str, Any]
    ) -> None:
        first = self._make_group(template_id=template_id, alert_id="alert-1", inputs=first_inputs)
        second = self._make_group(template_id=template_id, alert_id="alert-1", inputs=second_inputs)

        soft_delete_alert_destinations(
            team_id=self.team.id,
            alert_id="alert-1",
            allowed_event_ids=ALLOWED_EVENT_IDS,
            hog_function_ids=[destination.id for destination in first],
        )

        self._assert_deleted(first)
        self._assert_intact(second)

        soft_delete_alert_destinations(
            team_id=self.team.id,
            alert_id="alert-1",
            allowed_event_ids=ALLOWED_EVENT_IDS,
            hog_function_ids=[destination.id for destination in second],
        )

        self._assert_deleted(second)

    def test_destination_missing_an_event_kind_is_still_deletable(self) -> None:
        destinations = [
            self._make_hog_function(template_id="template-slack", alert_id="alert-1", event_id=event_id)
            for event_id in ALLOWED_EVENT_IDS[:-1]
        ]

        soft_delete_alert_destinations(
            team_id=self.team.id,
            alert_id="alert-1",
            allowed_event_ids=ALLOWED_EVENT_IDS,
            hog_function_ids=[destination.id for destination in destinations],
        )

        self._assert_deleted(destinations)

    def test_a_disabled_row_must_be_deleted_with_the_rest_of_its_group(self) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")
        HogFunction.objects.filter(id=destinations[0].id).update(enabled=False)

        with self.assertRaisesRegex(ValidationError, "Delete all destinations in this group"):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id for destination in destinations[1:]],
            )

        assert HogFunction.objects.filter(
            id__in=[destination.id for destination in destinations], deleted=False
        ).count() == len(destinations)

        soft_delete_alert_destinations(
            team_id=self.team.id,
            alert_id="alert-1",
            allowed_event_ids=ALLOWED_EVENT_IDS,
            hog_function_ids=[destination.id for destination in destinations],
        )

        self._assert_deleted(destinations)

    def test_rejects_partial_group_when_another_destination_of_the_same_type_exists(self) -> None:
        first = self._make_group(template_id="template-slack", alert_id="alert-1", inputs=slack_inputs("C-ENG"))
        second = self._make_group(template_id="template-slack", alert_id="alert-1", inputs=slack_inputs("C-OPS"))

        with self.assertRaisesRegex(ValidationError, "Delete all destinations in this group"):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[first[0].id, *(destination.id for destination in second)],
            )

        self._assert_intact([*first, *second])

    def test_deletes_a_pre_existing_duplicate_pair_together(self) -> None:
        first = self._make_group(template_id="template-webhook", alert_id="alert-1", inputs=webhook_inputs("https://x"))
        second = self._make_group(
            template_id="template-webhook", alert_id="alert-1", inputs=webhook_inputs("https://x")
        )

        soft_delete_alert_destinations(
            team_id=self.team.id,
            alert_id="alert-1",
            allowed_event_ids=ALLOWED_EVENT_IDS,
            hog_function_ids=[destination.id for destination in (*first, *second)],
        )

        self._assert_deleted([*first, *second])

    def test_rejects_deleting_half_of_a_pre_existing_duplicate_pair(self) -> None:
        first = self._make_group(template_id="template-webhook", alert_id="alert-1", inputs=webhook_inputs("https://x"))
        second = self._make_group(
            template_id="template-webhook", alert_id="alert-1", inputs=webhook_inputs("https://x")
        )

        with self.assertRaisesRegex(ValidationError, "Delete all destinations in this group"):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id for destination in first],
            )

        self._assert_intact([*first, *second])

    def test_rejects_partial_delete_when_a_row_config_cannot_be_read(self) -> None:
        orphan = self._make_hog_function(template_id="template-slack", alert_id="alert-1", inputs={})
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        with self.assertRaisesRegex(ValidationError, "can no longer be read"):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id for destination in destinations],
            )

        self._assert_intact([orphan, *destinations])

    def test_rejects_deleting_only_the_row_whose_config_cannot_be_read(self) -> None:
        orphan = self._make_hog_function(template_id="template-slack", alert_id="alert-1", inputs={})
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        with self.assertRaisesRegex(ValidationError, "can no longer be read"):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[orphan.id],
            )

        self._assert_intact([orphan, *destinations])

    def test_deletes_every_row_of_a_template_that_has_an_unreadable_config(self) -> None:
        orphan = self._make_hog_function(template_id="template-slack", alert_id="alert-1", inputs={})
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        soft_delete_alert_destinations(
            team_id=self.team.id,
            alert_id="alert-1",
            allowed_event_ids=ALLOWED_EVENT_IDS,
            hog_function_ids=[orphan.id, *(destination.id for destination in destinations)],
        )

        self._assert_deleted([orphan, *destinations])

    def test_unreadable_config_does_not_block_deleting_another_template(self) -> None:
        orphan = self._make_hog_function(template_id="template-slack", alert_id="alert-1", inputs={})
        webhooks = self._make_group(template_id="template-webhook", alert_id="alert-1")

        soft_delete_alert_destinations(
            team_id=self.team.id,
            alert_id="alert-1",
            allowed_event_ids=ALLOWED_EVENT_IDS,
            hog_function_ids=[destination.id for destination in webhooks],
        )

        self._assert_deleted(webhooks)
        self._assert_intact([orphan])

    @patch("products.alerts.backend.destinations.logger")
    @patch("products.alerts.backend.destinations.posthoganalytics.capture")
    def test_unreadable_config_is_captured_and_logged(self, capture, logger) -> None:
        self._make_hog_function(template_id="template-slack", alert_id="alert-1", inputs={})
        webhooks = self._make_group(template_id="template-webhook", alert_id="alert-1")

        soft_delete_alert_destinations(
            team_id=self.team.id,
            alert_id="alert-1",
            allowed_event_ids=ALLOWED_EVENT_IDS,
            hog_function_ids=[destination.id for destination in webhooks],
        )

        capture.assert_called_once_with(
            distinct_id=f"team_{self.team.id}",
            event="alert destination config unreadable",
            properties={
                "alert_id": "alert-1",
                "feature": "alerts",
                "row_count": 1,
                "team_id": self.team.id,
                "template_id": "template-slack",
            },
        )
        assert logger.warning.call_args.args == ("Alert destination config could not be read",)
        assert logger.warning.call_args.kwargs["row_counts_by_template"] == {"template-slack": 1}

    def test_rejects_destinations_belonging_to_another_alert(self) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")
        other_alert = self._make_group(template_id="template-slack", alert_id="alert-2")

        with self.assertRaisesRegex(ValidationError, "do not belong to this alert"):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id for destination in other_alert],
            )

        self._assert_intact([*destinations, *other_alert])

    def test_rejects_destinations_belonging_to_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_team_destinations = self._make_group(template_id="template-slack", alert_id="alert-1", team=other_team)

        with self.assertRaisesRegex(ValidationError, "do not belong to this alert"):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id for destination in other_team_destinations],
            )

        self._assert_intact(other_team_destinations)

    def test_deletes_every_destination_of_the_alert_including_same_type_siblings(self) -> None:
        first = self._make_group(template_id="template-slack", alert_id="alert-1", inputs=slack_inputs("C-ENG"))
        second = self._make_group(template_id="template-slack", alert_id="alert-1", inputs=slack_inputs("C-OPS"))
        other_alert = self._make_group(template_id="template-slack", alert_id="alert-2")

        deleted_count = soft_delete_all_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=ALLOWED_EVENT_IDS
        )

        assert deleted_count == len(first) + len(second)
        self._assert_deleted([*first, *second])
        self._assert_intact(other_alert)

    def test_reports_invalid_ids_and_does_not_delete_any_destinations(self) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")
        other = self._make_hog_function(template_id="template-webhook", alert_id="alert-1", event_id="$unrelated_event")

        with self.assertRaises(ValidationError) as error:
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destinations[0].id, other.id],
            )

        assert isinstance(error.exception.detail, dict)
        hog_function_id_errors = error.exception.detail["hog_function_ids"]
        assert isinstance(hog_function_id_errors, list)
        assert str(hog_function_id_errors[0]) == (
            f"These HogFunctions do not belong to this alert: {other.id}. Refresh the alert and try again."
        )
        self._assert_intact([*destinations, other])

    def test_deletes_all_destinations_for_alert_only(self) -> None:
        slack_destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")
        webhook_destination = self._make_hog_function(template_id="template-webhook", alert_id="alert-1")
        other_alert_destination = self._make_hog_function(template_id="template-slack", alert_id="alert-2")
        non_destination = self._make_hog_function(template_id="template-webhook-custom", alert_id="alert-1")
        unrelated_event_destination = self._make_hog_function(
            template_id="template-webhook", alert_id="alert-1", event_id="$unrelated_event"
        )

        deleted_count = soft_delete_all_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=ALLOWED_EVENT_IDS
        )

        assert deleted_count == 2
        self._assert_deleted([slack_destination, webhook_destination])
        self._assert_intact([other_alert_destination, non_destination, unrelated_event_destination])

    def test_rejects_empty_allowed_event_ids_without_deleting_destinations(self) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        with self.assertRaisesRegex(ValueError, "allowed_event_ids must not be empty"):
            soft_delete_all_alert_destinations(team_id=self.team.id, alert_id="alert-1", allowed_event_ids=())

        self._assert_intact(destinations)

    @patch("products.alerts.backend.destinations.reload_hog_functions_on_workers")
    def test_reload_happens_after_destination_delete_commits(self, reload_hog_functions_on_workers) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        with self.captureOnCommitCallbacks(execute=True):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id for destination in destinations],
            )
            reload_hog_functions_on_workers.assert_not_called()

        reload_hog_functions_on_workers.assert_called_once_with(
            team_id=self.team.id, hog_function_ids=sorted(str(destination.id) for destination in destinations)
        )

    @patch("products.alerts.backend.destinations.reload_hog_functions_on_workers", side_effect=RuntimeError("boom"))
    def test_reload_failure_does_not_fail_committed_delete(self, _reload_hog_functions_on_workers) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        with self.captureOnCommitCallbacks(execute=True):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id for destination in destinations],
            )

        self._assert_deleted(destinations)


class TestAlertInternalEventDelivery(APIBaseTest):
    @patch("products.alerts.backend.destinations.capture_exception")
    @patch("products.alerts.backend.destinations.ALERT_INTERNAL_EVENT_DELIVERY_FAILURES")
    def test_expected_delivery_failure_records_metric_without_capturing_exception(
        self, delivery_failures, capture_exception
    ) -> None:
        produce_result = MagicMock()
        produce_result.get.side_effect = RuntimeError("delivery failed")

        delivered = alert_internal_event_delivered(
            produce_result,
            team_id=self.team.id,
            alert_id="alert-1",
            event_name="$logs_alert_firing",
        )

        assert delivered is False
        capture_exception.assert_not_called()
        delivery_failures.labels.assert_called_once_with(event_name="$logs_alert_firing")
        delivery_failures.labels.return_value.inc.assert_called_once_with()


class TestListActiveAlertDestinations(AlertDestinationTestCase):
    def test_list_active_alert_destinations_returns_name_and_type(self) -> None:
        self._make_hog_function(
            template_id="template-slack", alert_id="alert-1", name="Alerts — Signups (firing) → Slack #eng-alerts"
        )
        self._make_hog_function(
            template_id="template-slack", alert_id="alert-1", name="Alerts — Signups (firing) → Slack #alerts"
        )
        self._make_hog_function(template_id="template-webhook", alert_id="alert-2")
        disabled = self._make_hog_function(template_id="template-slack", alert_id="alert-1", name="Disabled")
        disabled.enabled = False
        disabled.save()
        deleted = self._make_hog_function(template_id="template-slack", alert_id="alert-1", name="Deleted")
        deleted.deleted = True
        deleted.save()

        destinations = list_active_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=("$logs_alert_firing",)
        )
        names_and_types = [(d.name, d.destination_type) for d in destinations]

        assert ("Slack #eng-alerts", "slack") in names_and_types
        assert ("Slack #alerts", "slack") in names_and_types
        assert all(isinstance(d.id, str) for d in destinations)
        assert len(destinations) == 2

    @parameterized.expand(
        [
            ("alert_name_contains_separator", "Alerts — A → B (firing) → Slack #eng-alerts", "Slack #eng-alerts"),
            ("renamed_destination_has_no_separator", "My renamed destination", "My renamed destination"),
            ("name_clipped_before_separator", "Alerts — a very long alert name…", "Alerts — a very long alert name…"),
        ]
    )
    def test_destination_name_reduces_to_its_trailing_segment(
        self, _name: str, hog_function_name: str, expected: str
    ) -> None:
        self._make_hog_function(template_id="template-slack", alert_id="alert-1", name=hog_function_name)

        destinations = list_active_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=("$logs_alert_firing",)
        )

        assert [d.name for d in destinations] == [expected]

    @parameterized.expand(
        [
            ("userinfo_credentials_are_dropped", "https://user:s3cret@hooks.example.com/hook", "hooks.example.com"),
            ("uppercase_scheme_is_matched", "HTTPS://hooks.example.com/services/secret", "hooks.example.com"),
            ("non_http_scheme_is_matched", "ftp://hooks.example.com/secret", "hooks.example.com"),
            ("port_is_dropped", "https://hooks.example.com:8443/secret", "hooks.example.com"),
        ]
    )
    def test_receipt_names_keep_only_the_url_host(self, _name: str, url: str, expected_host: str) -> None:
        self._make_hog_function(
            template_id="template-webhook", alert_id="alert-1", name=f"Alerts — X (firing) → Webhook {url}"
        )

        destinations = list_active_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=("$logs_alert_firing",)
        )

        assert [d.name for d in destinations] == [f"Webhook {expected_host}"]

    def test_list_active_alert_destinations_strips_webhook_urls_to_host(self) -> None:
        # Webhook names embed the full URL, whose path is the channel credential —
        # receipts surface in the API and tooltip, so only the host may survive.
        self._make_hog_function(
            template_id="template-webhook",
            alert_id="alert-1",
            name="Alerts — Signups (firing) → Webhook https://discord.com/api/webhooks/123/secret-token",
        )

        destinations = list_active_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=("$logs_alert_firing",)
        )

        assert [d.name for d in destinations] == ["Webhook discord.com"]


class TestSerializeDeliveries(APIBaseTest):
    def test_serialize_deliveries_roundtrips_dataclass_fields(self) -> None:
        delivery = AlertDelivery(channel="email", target="a@example.com", at="2026-08-11T00:00:00+00:00")
        result = serialize_deliveries([delivery])

        assert result == [
            {
                "channel": "email",
                "target": "a@example.com",
                "target_id": None,
                "template": None,
                "status": "accepted",
                "at": "2026-08-11T00:00:00+00:00",
            }
        ]

    def test_serialize_deliveries_with_all_fields(self) -> None:
        delivery = AlertDelivery(
            channel="hog_function",
            target="Slack #general",
            target_id="hf-123",
            template="slack",
            status="accepted",
            at="2026-08-11T01:00:00+00:00",
        )
        result = serialize_deliveries([delivery])

        assert result == [
            {
                "channel": "hog_function",
                "target": "Slack #general",
                "target_id": "hf-123",
                "template": "slack",
                "status": "accepted",
                "at": "2026-08-11T01:00:00+00:00",
            }
        ]
