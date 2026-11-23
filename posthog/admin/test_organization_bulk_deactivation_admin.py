import re
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import Client, SimpleTestCase

from parameterized import parameterized
from structlog.testing import capture_logs

from posthog.admin.console.organization_shutdown import AUDIT_EVENT, PAUSE_NOTE, find_background_work
from posthog.admin.console.organization_tools import BulkDeactivateOrganizationsForm
from posthog.models import Organization, Team, User

from products.alerts.backend.models.alert import AlertConfiguration
from products.batch_exports.backend.facade.testing import create_batch_export
from products.cdp.backend.facade.models import HogFunction
from products.cdp.backend.models.plugin import Plugin, PluginConfig
from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade import api as subscriptions_facade
from products.subscriptions.backend.facade.testing import create_subscription
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.workflows.backend.facade.testing import create_workflow_for_test


class TestBulkDeactivateOrganizationsForm(SimpleTestCase):
    def test_defaults_to_desktop_abuse_reason_and_parses_pasted_ids(self) -> None:
        first_organization_id = uuid4()
        second_organization_id = uuid4()
        form = BulkDeactivateOrganizationsForm(
            {
                "organization_ids": f"{first_organization_id},\n{second_organization_id} {first_organization_id}",
                "reason": Organization.DeactivationReason.DESKTOP_ABUSE.value,
                "custom_reason": "",
            }
        )

        assert (
            BulkDeactivateOrganizationsForm().fields["reason"].initial == Organization.DeactivationReason.DESKTOP_ABUSE
        )
        assert form.is_valid()
        assert form.cleaned_data["organization_ids"] == [first_organization_id, second_organization_id]
        assert form.cleaned_data["resolved_reason"] == Organization.DeactivationReason.DESKTOP_ABUSE.value

    def test_custom_reason_is_required_when_custom_is_selected(self) -> None:
        organization_id = uuid4()
        form = BulkDeactivateOrganizationsForm(
            {
                "organization_ids": str(organization_id),
                "reason": BulkDeactivateOrganizationsForm.CUSTOM_REASON,
                "custom_reason": "",
            }
        )

        assert not form.is_valid()
        assert "custom_reason" in form.errors

    def test_rejects_invalid_uuid(self) -> None:
        organization_id = uuid4()
        form = BulkDeactivateOrganizationsForm(
            {
                "organization_ids": f"{organization_id},not-a-uuid",
                "reason": Organization.DeactivationReason.DESKTOP_ABUSE.value,
                "custom_reason": "",
            }
        )

        assert not form.is_valid()
        assert "organization_ids" in form.errors

    def test_rejects_more_than_max_organization_ids(self) -> None:
        form = BulkDeactivateOrganizationsForm(
            {
                "organization_ids": "\n".join(
                    str(uuid4()) for _ in range(BulkDeactivateOrganizationsForm.MAX_ORGANIZATIONS + 1)
                ),
                "reason": Organization.DeactivationReason.DESKTOP_ABUSE.value,
                "custom_reason": "",
            }
        )

        assert not form.is_valid()
        assert "organization_ids" in form.errors


TOOL_URL = "/admin/console/tools/bulk-deactivate-organizations/deactivate/"
DESKTOP_ABUSE = Organization.DeactivationReason.DESKTOP_ABUSE.value
COMPLIANCE_REVIEW = Organization.DeactivationReason.COMPLIANCE_REVIEW.value
SECURITY_VIOLATION = Organization.DeactivationReason.TERMS_OF_SERVICE_VIOLATION_SECURITY.value


class FakeTemporal:
    """Stands in for the Temporal client and records each schedule it was asked to pause."""

    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.paused: list[tuple[str, str | None]] = []
        self.failing = failing

    def get_schedule_handle(self, schedule_id: str) -> "FakeScheduleHandle":
        return FakeScheduleHandle(self, schedule_id)


class FakeScheduleHandle:
    def __init__(self, temporal: FakeTemporal, schedule_id: str) -> None:
        self.temporal = temporal
        self.schedule_id = schedule_id

    async def pause(self, note: str | None = None) -> None:
        if self.schedule_id in self.temporal.failing:
            raise RuntimeError("Temporal is unavailable")
        self.temporal.paused.append((self.schedule_id, note))


@contextmanager
def temporal_boundary(temporal: FakeTemporal) -> Iterator[None]:
    with (
        patch("products.batch_exports.backend.logic.exports.sync_connect", return_value=temporal),
        patch("products.data_warehouse.backend.logic.data_load.service.sync_connect", return_value=temporal),
    ):
        yield


def start_background_work(team: Team, user: User) -> dict[str, str]:
    """One running item of every kind a shutdown stops, by the label the console shows."""
    insight = Insight.objects.create(team=team, name="Signups")
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    plugin = Plugin.objects.create(organization=team.organization, name="Legacy plugin")
    return {
        "Destinations": str(
            HogFunction.objects.create(team=team, type="destination", enabled=True, hog="return event").id
        ),
        "Workflows": create_workflow_for_test(team_id=team.id, status="active").id,
        "Batch exports": str(
            create_batch_export(
                team.id, name="Export", destination_type="HTTP", destination_config={"url": "https://example.com"}
            )
        ),
        "Warehouse syncs": str(
            ExternalDataSchema.objects.create(team=team, source=source, name="orders", should_sync=True).id
        ),
        "Legacy plugins": str(PluginConfig.objects.create(plugin=plugin, team=team, enabled=True, order=0).id),
        "Subscriptions": str(create_subscription(team_id=team.id, insight_id=insight.id)),
        "Insight alerts": str(
            AlertConfiguration.objects.create(team=team, insight=insight, enabled=True, created_by=user).id
        ),
    }


def running_work(team: Team) -> dict[str, tuple[str, ...]]:
    return {work.label: work.ids for work in find_background_work([team.id]).running}


class TestBulkDeactivateOrganizationsTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _preview(
        self,
        organization_ids: str,
        reason: str = DESKTOP_ABUSE,
        custom_reason: str = "",
        stop_background_work: bool = False,
    ):
        data = {"organization_ids": organization_ids, "reason": reason, "custom_reason": custom_reason}
        if stop_background_work:
            data["stop_background_work"] = "on"
        return self.client.post(TOOL_URL, data)

    def _confirm_token(self, preview_response) -> str:
        match = re.search(r'name="confirm_token" value="([^"]+)"', preview_response.content.decode())
        assert match is not None, "The preview page has no confirm button"
        return match.group(1)

    def _deactivate(
        self,
        organization_ids: str,
        reason: str = DESKTOP_ABUSE,
        custom_reason: str = "",
        stop_background_work: bool = False,
    ):
        token = self._confirm_token(self._preview(organization_ids, reason, custom_reason, stop_background_work))
        return self.client.post(TOOL_URL, {"confirm_token": token})

    def _shut_down(self, organization_ids: str, temporal: FakeTemporal) -> str:
        token = self._confirm_token(self._preview(organization_ids, SECURITY_VIOLATION, stop_background_work=True))
        with temporal_boundary(temporal):
            response = self.client.post(TOOL_URL, {"confirm_token": token})
        assert response.status_code == 302
        return self.client.get(response["Location"]).content.decode()

    def test_preview_shows_matched_organizations_and_missing_ids_without_deactivating(self) -> None:
        missing_id = uuid4()
        start_background_work(self.team, self.user)
        running = running_work(self.team)

        response = self._preview(f"{self.organization.id}\n{missing_id}", stop_background_work=True)

        assert response.status_code == 200
        self.organization.refresh_from_db()
        assert self.organization.is_active
        content = response.content.decode()
        assert str(self.organization.id) in content
        assert str(missing_id) in content
        assert "Destinations: 1, Workflows: 1, Batch exports: 1, Warehouse syncs: 1" in content
        assert "Legacy plugins: 1, Subscriptions: 1, Insight alerts: 1" in content
        assert running_work(self.team) == running

    def test_confirm_shuts_down_the_organization_and_leaves_other_organizations_running(self) -> None:
        stopped = start_background_work(self.team, self.user)
        other_organization = Organization.objects.create(name="Legitimate")
        other_team = Team.objects.create(organization=other_organization, name="Legitimate team")
        start_background_work(other_team, self.user)
        other_running = running_work(other_team)
        temporal = FakeTemporal()

        with capture_logs() as logs:
            result = self._shut_down(str(self.organization.id), temporal)

        self.organization.refresh_from_db()
        assert (self.organization.is_active, self.organization.is_not_active_reason) == (False, SECURITY_VIOLATION)
        assert running_work(self.team) == {}
        assert running_work(other_team) == other_running
        assert sorted(temporal.paused) == sorted(
            [(stopped["Batch exports"], PAUSE_NOTE), (stopped["Warehouse syncs"], None)]
        )
        for resource_id in stopped.values():
            assert resource_id in result
        [audit] = [log for log in logs if log["event"] == AUDIT_EVENT]
        assert (audit["reason"], audit["stopped"]) == (
            SECURITY_VIOLATION,
            {label: [resource_id] for label, resource_id in stopped.items()},
        )

    @parameterized.expand([("an_item_fails_to_stop", "Batch exports"), ("a_kind_fails_to_list", "Subscriptions")])
    def test_a_failure_is_reported_and_the_rest_still_stop(self, _name: str, failing_kind: str) -> None:
        stopped = start_background_work(self.team, self.user)
        failing_id = stopped[failing_kind]
        temporal = FakeTemporal(failing=frozenset({failing_id}) if failing_kind == "Batch exports" else frozenset())

        listing_fails = (
            patch.object(subscriptions_facade, "enabled_subscription_ids", side_effect=RuntimeError("Database down"))
            if failing_kind == "Subscriptions"
            else nullcontext()
        )

        with listing_fails:
            preview = self._preview(str(self.organization.id), stop_background_work=True).content.decode()
            result = self._shut_down(str(self.organization.id), temporal)

        assert running_work(self.team) == {failing_kind: (failing_id,)}
        assert "A failure can come after the change was saved" in result
        assert ("BatchExportScheduleError" if failing_kind == "Batch exports" else "Could not list them") in result
        assert (failing_kind == "Subscriptions") == ("Subscriptions: could not list" in preview)

    def test_confirm_stops_the_work_of_an_organization_that_is_already_inactive(self) -> None:
        Organization.objects.filter(id=self.organization.id).update(
            is_active=False, is_not_active_reason=COMPLIANCE_REVIEW
        )
        start_background_work(self.team, self.user)

        self._shut_down(str(self.organization.id), FakeTemporal())

        self.organization.refresh_from_db()
        assert self.organization.is_not_active_reason == COMPLIANCE_REVIEW
        assert running_work(self.team) == {}

    @parameterized.expand(
        [
            ("preset_reason", DESKTOP_ABUSE, "", DESKTOP_ABUSE),
            (
                "custom_reason",
                BulkDeactivateOrganizationsForm.CUSTOM_REASON,
                "Manual review required.",
                "Manual review required.",
            ),
        ]
    )
    def test_confirm_deactivates_active_organizations_and_keeps_inactive_ones(
        self, _name: str, reason: str, custom_reason: str, expected_reason: str
    ) -> None:
        inactive = Organization.objects.create(
            name="Already inactive", is_active=False, is_not_active_reason=COMPLIANCE_REVIEW
        )
        start_background_work(self.team, self.user)
        running = running_work(self.team)

        response = self._deactivate(f"{self.organization.id}\n{inactive.id}\n{uuid4()}", reason, custom_reason)

        assert response.status_code == 302
        self.organization.refresh_from_db()
        inactive.refresh_from_db()
        assert (self.organization.is_active, self.organization.is_not_active_reason) == (False, expected_reason)
        assert (inactive.is_active, inactive.is_not_active_reason) == (False, COMPLIANCE_REVIEW)
        assert running_work(self.team) == running

    def test_confirm_keeps_the_reason_of_an_organization_deactivated_since_the_preview(self) -> None:
        token = self._confirm_token(self._preview(str(self.organization.id)))
        Organization.objects.filter(id=self.organization.id).update(
            is_active=False, is_not_active_reason=COMPLIANCE_REVIEW
        )

        self.client.post(TOOL_URL, {"confirm_token": token})

        self.organization.refresh_from_db()
        assert self.organization.is_not_active_reason == COMPLIANCE_REVIEW

    def test_preview_requires_at_least_one_active_organization(self) -> None:
        inactive = Organization.objects.create(name="Only inactive", is_active=False)

        response = self._preview(str(inactive.id))

        assert response.status_code == 400
        assert "All matched organizations are already inactive." in response.content.decode()

    @parameterized.expand([("tampered_token", "tampered"), ("another_staff_member", "other_user")])
    def test_confirm_refuses_a_token_it_did_not_issue_for_this_user(self, _name: str, case: str) -> None:
        token = self._confirm_token(self._preview(str(self.organization.id)))
        client = self.client
        if case == "tampered":
            token = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
        else:
            other = User.objects.create_and_join(self.organization, "other-staff@posthog.com", None, is_staff=True)
            client = Client()
            client.force_login(other)

        response = client.post(TOOL_URL, {"confirm_token": token})

        assert response.status_code == 302
        assert response["Location"] == TOOL_URL
        self.organization.refresh_from_db()
        assert self.organization.is_active


class TestShutDownOrganizationOperation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_runs_the_same_shutdown_as_the_bulk_tool(self) -> None:
        url = f"/admin/console/organizations/{self.organization.pk}/background-work/shut-down/"
        stopped = start_background_work(self.team, self.user)
        preview = self.client.post(
            url, {"reason": SECURITY_VIOLATION, "custom_reason": "", "stop_background_work": "on"}
        )
        assert "Destinations: 1" in preview.content.decode()
        token = re.search(r'name="confirm_token" value="([^"]+)"', preview.content.decode())
        assert token is not None
        temporal = FakeTemporal()

        with temporal_boundary(temporal):
            response = self.client.post(url, {"confirm_token": token.group(1)})

        self.organization.refresh_from_db()
        assert (self.organization.is_active, self.organization.is_not_active_reason) == (False, SECURITY_VIOLATION)
        assert running_work(self.team) == {}
        result = self.client.get(response["Location"]).content.decode()
        assert stopped["Destinations"] in result
