from io import StringIO

import pytest

from django.core.management import call_command

from rest_framework import status

from posthog.models.organization import OrganizationMembership

from products.access_control.backend.resolution_preview import build_resolution_preview
from products.access_control.backend.tests.test_user_access_control import BaseUserAccessControlTest
from products.dashboards.backend.models.dashboard import Dashboard


@pytest.mark.ee
class TestBuildResolutionPreview(BaseUserAccessControlTest):
    def setUp(self):
        super().setUp()
        self.other_membership = OrganizationMembership.objects.get(user=self.other_user, organization=self.organization)
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.user, name="Growth KPIs")

    def _changes(self):
        return build_resolution_preview(self.team, self.user_access_control)

    def test_object_default_change_is_one_everyone_record(self):
        # The change reaches every member without a more specific rule, but it is one rule:
        # per-member records would explode a default change into the whole project roster
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="viewer")
        self._create_access_control(resource="dashboard", access_level="editor")

        changes = self._changes()

        assert len(changes) == 1
        change = changes[0]
        assert change.subject.type == "everyone"
        assert change.scope == "object"
        assert change.object_id == str(self.dashboard.id)
        assert change.object_name == "Growth KPIs"
        assert (change.current.level, change.current.source) == ("editor", "resource")
        assert (change.proposed.level, change.proposed.source) == ("viewer", "object")
        assert change.direction == "loses"

    def test_member_override_produces_member_record_only(self):
        # other_user holds role_b (base fixture). Today the role's grant applies; after the
        # change their own override applies. The role itself resolves the same both ways, so
        # only the member record is reported, not one row per role member.
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.dashboard.id),
            access_level="none",
            organization_member=self.other_membership,
        )
        self._create_access_control(
            resource="dashboard", resource_id=str(self.dashboard.id), access_level="editor", role=self.role_b
        )

        changes = self._changes()

        assert len(changes) == 1
        change = changes[0]
        assert change.subject.type == "member"
        assert change.subject.id == str(self.other_membership.id)
        assert (change.current.level, change.proposed.level) == ("editor", "none")
        assert change.proposed.source_subject == "member"
        assert change.direction == "loses"

    def test_resource_scope_member_below_role_is_one_record(self):
        # other_user holds role_b (base fixture); their own resource-wide "none" starts applying
        self._create_access_control(
            resource="dashboard", access_level="none", organization_member=self.other_membership
        )
        self._create_access_control(resource="dashboard", access_level="editor", role=self.role_b)

        changes = self._changes()

        assert len(changes) == 1
        change = changes[0]
        assert change.scope == "resource"
        assert change.subject.type == "member"
        assert (change.current.level, change.proposed.level) == ("editor", "none")

    def test_creator_pairs_are_skipped(self):
        # Creators keep the highest level under both ladders, so their override never applies
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)
        self._create_access_control(
            resource="dashboard",
            resource_id=str(dashboard.id),
            access_level="none",
            organization_member=self.other_membership,
        )
        self._create_access_control(resource="dashboard", resource_id=str(dashboard.id), access_level="editor")

        changes = self._changes()

        assert [change for change in changes if change.subject.type == "member"] == []

    def test_org_admin_members_are_skipped(self):
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.dashboard.id),
            access_level="none",
            organization_member=self.other_membership,
        )
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="editor")
        self.other_membership.level = OrganizationMembership.Level.ADMIN
        self.other_membership.save()

        changes = self._changes()

        assert [change for change in changes if change.subject.type == "member"] == []

    def test_no_entitlement_returns_no_changes(self):
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="viewer")
        self._create_access_control(resource="dashboard", access_level="editor")
        self.organization.available_product_features = []
        self.organization.save()

        assert self._changes() == []


@pytest.mark.ee
class TestResolutionPreviewAPI(BaseUserAccessControlTest):
    def setUp(self):
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user, name="Growth KPIs")
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="viewer")
        self._create_access_control(resource="dashboard", access_level="editor")
        self.membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.client.force_login(self.user)

    def test_requires_admin(self):
        response = self.client.get("/api/projects/@current/access_control_resolution_preview")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_returns_changes_and_summary(self):
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()

        response = self.client.get("/api/projects/@current/access_control_resolution_preview")

        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        assert data["summary"]["total"] == 1
        assert data["summary"]["loses"] == 1
        change = data["changes"][0]
        assert change["subject"] == {"type": "everyone", "id": None, "name": "Everyone"}
        assert change["object_name"] == "Growth KPIs"
        assert change["current"] == {
            "level": "editor",
            "source": "resource",
            "source_subject": "default",
            "subject_name": None,
        }
        assert change["proposed"] == {
            "level": "viewer",
            "source": "object",
            "source_subject": "default",
            "subject_name": None,
        }


@pytest.mark.ee
class TestFindDivergentAccessOrgsCommand(BaseUserAccessControlTest):
    def test_lists_divergent_org(self):
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        self._create_access_control(resource="dashboard", resource_id=str(dashboard.id), access_level="viewer")
        self._create_access_control(resource="dashboard", access_level="editor")

        out = StringIO()
        call_command("migrate_to_most_specific_access", "--dry-run", stdout=out)

        assert str(self.organization.id) in out.getvalue()

    def test_single_org_report_lists_change_records(self):
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user, name="Growth KPIs")
        self._create_access_control(resource="dashboard", resource_id=str(dashboard.id), access_level="viewer")
        self._create_access_control(resource="dashboard", access_level="editor")

        out = StringIO()
        call_command("preview_most_specific_access_changes", str(self.organization.id), stdout=out)

        output = out.getvalue()
        assert f"Project {self.team.pk}" in output
        assert 'dashboard "Growth KPIs"' in output
        assert "editor -> viewer (loses)" in output
