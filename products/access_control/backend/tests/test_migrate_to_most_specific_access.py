from io import StringIO

import pytest

from django.core.management import call_command

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.most_specific_migration import (
    enable_most_specific_resolution,
    find_organizations_to_migrate,
)
from products.access_control.backend.facade.resolution_preview import iter_resolution_changes
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.tests.test_user_access_control import BaseUserAccessControlTest
from products.dashboards.backend.models.dashboard import Dashboard


@pytest.mark.ee
class TestMigrateToMostSpecificAccess(BaseUserAccessControlTest):
    def setUp(self) -> None:
        super().setUp()
        # self.organization resolves differently: the resource-level editor row beats the
        # object's own viewer row under the legacy resolution only
        self.organization.uses_most_specific_access_resolution = False
        self.organization.save()
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user, name="Growth KPIs")
        self._create_access_control(resource="dashboard", resource_id=str(dashboard.id), access_level="viewer")
        self._create_access_control(resource="dashboard", access_level="editor")

        self.unchanged_organization = self._create_legacy_organization("Unchanged org")
        team = Team.objects.create(organization=self.unchanged_organization, name="Unchanged team")
        User.objects.create_and_join(self.unchanged_organization, "unchanged@posthog.com", "testtest")
        AccessControl.objects.create(team=team, resource="dashboard", access_level="viewer")

        self.unevaluated_organization = self._create_legacy_organization("No member org")
        team = Team.objects.create(organization=self.unevaluated_organization, name="No member team")
        AccessControl.objects.create(team=team, resource="dashboard", access_level="viewer")

        self.organization_without_rules = self._create_legacy_organization("No rules org")

    def _create_legacy_organization(self, name: str) -> Organization:
        return Organization.objects.create(
            name=name,
            uses_most_specific_access_resolution=False,
            available_product_features=[
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ],
        )

    def _resolution_flags(self) -> dict[str, bool]:
        return {
            org.name: org.uses_most_specific_access_resolution
            for org in Organization.objects.filter(
                id__in=[
                    self.organization.id,
                    self.unchanged_organization.id,
                    self.unevaluated_organization.id,
                    self.organization_without_rules.id,
                ]
            )
        }

    def test_migrates_only_organizations_the_change_does_not_affect(self) -> None:
        out = StringIO()
        call_command("migrate_to_most_specific_access", stdout=out)

        assert self._resolution_flags() == {
            self.organization.name: False,
            "Unchanged org": True,
            "No member org": False,
            "No rules org": True,
        }
        assert f"{self.organization.id}\t{self.organization.name}\tteams=1\tchanges=1" in out.getvalue()
        assert f"{self.unevaluated_organization.id}\tNo member org" in out.getvalue()

    def test_dry_run_reports_but_migrates_nothing(self) -> None:
        out = StringIO()
        call_command("migrate_to_most_specific_access", "--dry-run", stdout=out)

        assert self._resolution_flags() == {
            self.organization.name: False,
            "Unchanged org": False,
            "No member org": False,
            "No rules org": False,
        }
        assert "would be migrated" in out.getvalue()

    def test_object_rules_the_preview_cannot_resolve_stay_on_legacy(self) -> None:
        # No model backs the account resource, so an empty preview proves nothing for this organization
        team = self.unchanged_organization.teams.get()
        AccessControl.objects.create(team=team, resource="account", resource_id="1", access_level="none")
        out = StringIO()
        call_command("migrate_to_most_specific_access", stdout=out)

        assert self._resolution_flags()["Unchanged org"] is False
        assert f"{self.unchanged_organization.id}\tUnchanged org" in out.getvalue().split("could not be evaluated")[1]

    def test_object_rules_on_a_resource_the_preview_skips_do_not_block_the_switch(self) -> None:
        # Plugin rules are left out of the comparison on purpose, so they say nothing about resolvability
        team = self.unchanged_organization.teams.get()
        AccessControl.objects.create(team=team, resource="plugin", resource_id="1", access_level="none")
        call_command("migrate_to_most_specific_access", stdout=StringIO())

        assert self._resolution_flags()["Unchanged org"] is True

    def test_single_organization_preview_still_sees_rules_it_cannot_resolve(self) -> None:
        team = self.unchanged_organization.teams.get()
        AccessControl.objects.create(team=team, resource="account", resource_id="1", access_level="none")

        teams = [team for team, _ in iter_resolution_changes(str(self.unchanged_organization.id))]

        assert teams == [team]

    def test_rules_written_after_the_classification_block_the_switch(self) -> None:
        candidates = find_organizations_to_migrate()
        team = self.unchanged_organization.teams.get()
        AccessControl.objects.create(team=team, resource="insight", access_level="editor")

        updated = enable_most_specific_resolution(candidates.unaffected_ids, rules_unchanged_since=candidates.found_at)

        assert updated == 1  # only "No rules org"
        assert self._resolution_flags() == {
            self.organization.name: False,
            "Unchanged org": False,
            "No member org": False,
            "No rules org": True,
        }

    def test_skips_organizations_already_on_most_specific_resolution(self) -> None:
        self.unchanged_organization.uses_most_specific_access_resolution = True
        self.unchanged_organization.save()
        out = StringIO()
        call_command("migrate_to_most_specific_access", stdout=out)

        assert "Unchanged org" not in out.getvalue()
