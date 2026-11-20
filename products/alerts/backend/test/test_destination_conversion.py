from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any, cast
from uuid import UUID

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.management import call_command
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.alerts.backend.platform_cutover import cut_over_team
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import (
    create_alert_destinations,
    delete_source_destination_rows,
    list_alert_destinations,
)
from products.alerts_platform.backend.facade.contracts import AlertDestinationData, AlertEventKind, NewAlertDestination
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.cdp.backend.facade.models import HogFunction
from products.cdp.backend.templates.fixtures import template_pagerduty, template_slack, template_webhook
from products.cdp.backend.templates.hog_function_template import sync_template_to_db

WEBHOOK = {"type": "webhook", "webhook_url": "https://hooks.example.com/secret"}
PAGERDUTY = {"pagerduty_routing_key": "a" * 32}
TERRAFORM_USER_AGENT = "posthog/terraform-provider; version: 1.0.32"


class TestConvertInsightAlertDestinations(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        for reload in (
            "products.alerts.backend.logic.destinations.reload_hog_functions_on_workers",
            "products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers",
        ):
            reload_patcher = patch(reload)
            reload_patcher.start()
            self.addCleanup(reload_patcher.stop)
        for template in (template_slack, template_webhook, template_pagerduty):
            sync_template_to_db(template)
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"authed_user": {"id": "u"}},
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.slack = {"type": "slack", "slack_workspace_id": integration.id, "slack_channel_id": "C123"}
        self.url = f"/api/projects/{self.team.id}/alerts"
        self.now = datetime.now(UTC)

    def _alerts(self, count: int) -> list[UUID]:
        alerts = [
            create_insight_alert(self.team, name=f"alert {index}", next_check_at=self.now + timedelta(minutes=3))
            for index in range(count)
        ]
        cutovers = cut_over_team(self.team.id, now=self.now)
        assert [cutover.skipped for cutover in cutovers] == [None] * count
        return [alert.id for alert in alerts]

    def _copy_id(self, alert_id: UUID) -> UUID:
        with team_scope(self.team.id):
            return platform_testing.copy_of(alert_id).id

    def _add_stock_destination(self, alert_id: UUID, route: str, payload: dict[str, Any]) -> list[str]:
        # The alert page writes HogFunctions only for an alert the platform does not evaluate, which is how
        # every destination added before row-only creates looks.
        with team_scope(self.team.id):
            platform_testing.set_owner(self._copy_id(alert_id), PlatformAlertOwner.SOURCE)
        created = self.client.post(f"{self.url}/{alert_id}/destinations/{route}", payload, format="json")
        with team_scope(self.team.id):
            platform_testing.set_owner(self._copy_id(alert_id), PlatformAlertOwner.PLATFORM)
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        assert created.json()["hog_function_ids"]
        return created.json()["hog_function_ids"]

    def _rows(self, alert_id: UUID) -> list[Any]:
        return list(list_alert_destinations(team_id=self.team.id, configuration_id=self._copy_id(alert_id)))

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("convert_insight_alert_destinations", "--team-id", str(self.team.id), *args, stdout=out)
        return out.getvalue()

    def _live(self, hog_function_ids: list[str]) -> int:
        return HogFunction.objects.filter(id__in=hog_function_ids, deleted=False).count()

    @parameterized.expand(
        [
            ("added_before_rows", False, True),
            ("already_copied_by_a_row", True, True),
            ("switched_off_after_the_row_copied_it", True, False),
        ]
    )
    def test_a_stock_slack_group_becomes_one_row_and_its_hog_function_retires(
        self, _name: str, has_row: bool, enabled: bool
    ) -> None:
        (alert_id,) = self._alerts(1)
        hog_function_ids = self._add_stock_destination(alert_id, "", self.slack)
        if not enabled:
            HogFunction.objects.filter(id__in=hog_function_ids).update(enabled=False)
        if not has_row:
            (row,) = self._rows(alert_id)
            delete_source_destination_rows(
                team_id=self.team.id, public_id=alert_id, destination_ids=[row.id], hog_function_ids=()
            )
        rows_before = [row.id for row in self._rows(alert_id)]

        dry_run = self._run()

        assert f"{{'{'kept_row' if has_row else 'converted'}': 1}}" in dry_run
        assert self._live(hog_function_ids) == 1
        assert [row.id for row in self._rows(alert_id)] == rows_before

        self._run("--apply")

        (row,) = self._rows(alert_id)
        if has_row:
            assert [row.id] == rows_before
        assert [str(i) for i in row.legacy_hog_function_ids] == hog_function_ids
        assert (row.enabled, row.data["slack_channel_id"], tuple(row.event_kinds)) == (
            enabled,
            "C123",
            (AlertEventKind.FIRING,),
        )
        assert self._live(hog_function_ids) == 0

        again = self._run("--apply")

        assert "no HogFunction destinations" in again
        assert [r.id for r in self._rows(alert_id)] == [row.id]

    @patch("products.alerts.backend.presentation.views.alert.trigger_alert_hog_functions", return_value=[])
    def test_a_converted_slack_destination_lists_sends_natively_once_and_deletes_from_the_alert_page(
        self, trigger_hog_functions: Any
    ) -> None:
        (alert_id,) = self._alerts(1)
        self._add_stock_destination(alert_id, "", self.slack)
        destinations_url = f"{self.url}/{alert_id}/destinations/"

        self._run("--apply")

        (listed,) = self.client.get(destinations_url).json()
        (row,) = self._rows(alert_id)
        assert (listed["id"], listed["hog_function_ids"], listed["type"], listed["hears_firing"]) == (
            str(row.id),
            [],
            "slack",
            True,
        )
        with patch(
            "slack_sdk.WebClient.chat_postMessage", return_value={"ok": True, "channel": "C123", "ts": "1.0"}
        ) as chat_post_message:
            tested = self.client.post(f"{self.url}/{alert_id}/test-delivery/")
        assert tested.status_code == status.HTTP_202_ACCEPTED, tested.json()
        assert (chat_post_message.call_count, trigger_hog_functions.call_count) == (1, 0)

        deleted = self.client.post(f"{destinations_url}delete/", {"destination_ids": [listed["id"]]}, format="json")

        assert deleted.status_code in (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT), deleted.content
        assert self.client.get(destinations_url).json() == []

    @parameterized.expand(
        [
            ("team_keeps_the_legacy_body", True, False, "legacy_webhook_body"),
            ("alert_sends_on_hog_functions_for_a_customized_destination", False, True, "legacy_webhook_body"),
            ("alertmanager_body_already_sent_natively", False, False, None),
        ]
    )
    def test_a_webhook_converts_only_where_its_receiver_already_gets_the_native_body(
        self, _name: str, team_keeps_legacy_body: bool, has_customized: bool, outcome: str | None
    ) -> None:
        (alert_id,) = self._alerts(1)
        webhook_ids = self._add_stock_destination(alert_id, "webhook/", WEBHOOK)
        if has_customized:
            (slack_id,) = self._add_stock_destination(alert_id, "", self.slack)
            edited = self.client.patch(
                f"/api/projects/{self.team.id}/hog_functions/{slack_id}/",
                {"hog": "fetch('https://relay.example.com')"},
                format="json",
            )
            assert edited.status_code == status.HTTP_200_OK, edited.json()

        with patch(
            "products.alerts.backend.logic.delivery_path.keeps_legacy_webhook_body",
            return_value=team_keeps_legacy_body,
        ):
            out = self._run("--apply")

        if outcome is None:
            assert self._live(webhook_ids) == 0
        else:
            assert f"hog_functions={webhook_ids[0]} outcome={outcome}" in out
            assert self._live(webhook_ids) == 1

    def test_groups_that_cannot_convert_keep_their_hog_functions_and_print_why(self) -> None:
        (
            customized_alert,
            terraform_alert,
            pagerduty_alert,
            firing_alert,
            emitting_alert,
            duplicated_alert,
            refused_alert,
        ) = self._alerts(7)
        customized_ids = self._add_stock_destination(customized_alert, "", self.slack)
        edited = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{customized_ids[0]}/",
            {"hog": "fetch('https://relay.example.com')"},
            format="json",
        )
        assert edited.status_code == status.HTTP_200_OK, edited.json()
        terraform_ids = self._add_stock_destination(terraform_alert, "", self.slack)
        read = self.client.get(
            f"/api/projects/{self.team.id}/hog_functions/{terraform_ids[0]}/", HTTP_USER_AGENT=TERRAFORM_USER_AGENT
        )
        assert read.status_code == status.HTTP_200_OK, read.json()
        pagerduty_ids = self._add_stock_destination(pagerduty_alert, "pagerduty/", PAGERDUTY)
        firing_ids = self._add_stock_destination(firing_alert, "", self.slack)
        emitting_ids = self._add_stock_destination(emitting_alert, "", self.slack)
        # A second HogFunction with the same settings joins the first one's group, which the row copies only
        # part of, and which is only partly on.
        (duplicated_id,) = self._add_stock_destination(duplicated_alert, "", self.slack)
        duplicate = HogFunction.objects.get(id=duplicated_id)
        duplicate.pk = None
        duplicate.enabled = False
        duplicate.save()
        refused_ids = self._add_stock_destination(refused_alert, "", self.slack)
        (refused_row,) = self._rows(refused_alert)
        delete_source_destination_rows(
            team_id=self.team.id, public_id=refused_alert, destination_ids=[refused_row.id], hog_function_ids=()
        )
        with team_scope(self.team.id):
            create_alert_destinations(
                team_id=self.team.id,
                configuration_id=self._copy_id(refused_alert),
                destinations=(
                    NewAlertDestination(
                        data=cast(AlertDestinationData, self.slack), event_kinds=(AlertEventKind.FIRING,)
                    ),
                ),
            )
            platform_testing.start_firing(self._copy_id(firing_alert), team_id=self.team.id, at=timezone.now())
            platform_testing.record_legacy_emission(
                self._copy_id(emitting_alert), team_id=self.team.id, at=timezone.now() - timedelta(minutes=1)
            )

        dry_run = self._run()
        out = self._run("--apply")

        assert "'terraform_held': 1" in dry_run
        printed = {
            (fields["alert"], fields["outcome"])
            for line in out.splitlines()
            if line.startswith("alert=")
            for fields in [dict(field.split("=", 1) for field in line.split(" ")[:3])]
        }
        for alert_id, hog_function_ids, outcome in (
            (customized_alert, customized_ids, "customized"),
            (terraform_alert, terraform_ids, "terraform_held"),
            (pagerduty_alert, pagerduty_ids, "pagerduty_not_native"),
            (firing_alert, firing_ids, "firing"),
            (emitting_alert, emitting_ids, "recently_emitted"),
            (duplicated_alert, [duplicated_id, str(duplicate.pk)], "partly_enabled"),
            (refused_alert, refused_ids, "refused"),
        ):
            assert (str(alert_id), outcome) in printed, out
            assert self._live(hog_function_ids) == len(hog_function_ids), outcome

        HogFunction.objects.filter(id=duplicate.pk).update(enabled=True)

        assert "outcome=partly_copied" in self._run("--apply")
