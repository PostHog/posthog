from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.models.dashboard import Dashboard


class TestMigrateDashboardCollaborators(BaseTest):
    def test_dry_run_and_rerun_are_safe(self) -> None:
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Restricted dashboard",
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        args = [f"--org-ids={self.organization.id}"]
        dry_run_output = StringIO()

        call_command("migrate_dashboard_collaborators", *args, "--dry-run", stdout=dry_run_output)

        dashboard.refresh_from_db()
        assert dashboard.restriction_level == Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        assert not AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard.id)).exists()
        assert "Would migrate 1 dashboard across 1 organization." in dry_run_output.getvalue()

        call_command("migrate_dashboard_collaborators", *args)
        dashboard.refresh_from_db()
        assert dashboard.restriction_level == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        access_controls = AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard.id))
        assert access_controls.count() == 1
        assert access_controls.get().access_level == "viewer"

        call_command("migrate_dashboard_collaborators", *args, stdout=StringIO())
        assert access_controls.count() == 1
