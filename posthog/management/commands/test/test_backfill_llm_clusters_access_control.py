import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command

try:
    from ee.models.rbac.access_control import AccessControl
    from ee.models.rbac.role import Role
except ImportError:
    pass


@pytest.mark.ee
class TestBackfillLlmClustersAccessControl(BaseTest):
    def _llm_clusters_row(self, **filters):
        return AccessControl.objects.filter(resource="llm_clusters", **filters).first()

    def test_backfills_member_scoped_row(self):
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=None,
            access_level="viewer",
            organization_member=self.organization_membership,
        )

        call_command("backfill_llm_clusters_access_control")

        backfilled = self._llm_clusters_row(team=self.team, organization_member=self.organization_membership)
        assert backfilled is not None
        assert backfilled.access_level == "viewer"

    def test_backfills_role_scoped_row(self):
        role = Role.objects.create(name="Engineering", organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=None,
            access_level="editor",
            role=role,
        )

        call_command("backfill_llm_clusters_access_control")

        backfilled = self._llm_clusters_row(team=self.team, role=role)
        assert backfilled is not None
        assert backfilled.access_level == "editor"

    def test_backfills_org_default_row(self):
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=None,
            access_level="none",
            organization_member=None,
            role=None,
        )

        call_command("backfill_llm_clusters_access_control")

        backfilled = self._llm_clusters_row(team=self.team, organization_member=None, role=None)
        assert backfilled is not None
        assert backfilled.access_level == "none"

    def test_does_not_touch_other_resources(self):
        AccessControl.objects.create(
            team=self.team,
            resource="dataset",
            resource_id=None,
            access_level="editor",
            organization_member=self.organization_membership,
        )

        call_command("backfill_llm_clusters_access_control")

        assert not AccessControl.objects.filter(resource="llm_clusters").exists()

    def test_does_not_overwrite_existing_llm_clusters_row(self):
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=None,
            access_level="editor",
            organization_member=self.organization_membership,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="llm_clusters",
            resource_id=None,
            access_level="none",
            organization_member=self.organization_membership,
        )

        call_command("backfill_llm_clusters_access_control")

        rows = AccessControl.objects.filter(resource="llm_clusters", organization_member=self.organization_membership)
        assert rows.count() == 1
        row = rows.first()
        assert row is not None
        assert row.access_level == "none"

    def test_dry_run_does_not_write(self):
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=None,
            access_level="viewer",
            organization_member=self.organization_membership,
        )

        call_command("backfill_llm_clusters_access_control", "--dry-run")

        assert not AccessControl.objects.filter(resource="llm_clusters").exists()

    def test_idempotent_on_repeat_run(self):
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=None,
            access_level="viewer",
            organization_member=self.organization_membership,
        )

        call_command("backfill_llm_clusters_access_control")
        call_command("backfill_llm_clusters_access_control")

        rows = AccessControl.objects.filter(resource="llm_clusters", organization_member=self.organization_membership)
        assert rows.count() == 1
