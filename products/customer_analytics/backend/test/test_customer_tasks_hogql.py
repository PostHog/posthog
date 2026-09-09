from posthog.test.base import NonAtomicBaseTest

from django.utils import timezone

from posthog.hogql.query import execute_hogql_query

from posthog.models import OrganizationMembership, Team, User
from posthog.models.organization import AvailableFeature

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.facade import api, contracts
from products.customer_analytics.backend.models import Account
from products.customer_analytics.backend.models.customer_task import CustomerTask


class TestCustomerTasksHogqlAccess(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_task_visibility_matches_rest_listing(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        viewer = User.objects.create_and_join(self.organization, "task-hogql-viewer@example.com", "testtest")
        membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        visible_account = Account.objects.for_team(self.team.id).create(team=self.team, name="Visible account")
        hidden_account = Account.objects.for_team(self.team.id).create(team=self.team, name="Hidden account")
        other_team = Team.objects.create(organization=self.organization)

        for name, account, creator, team, archived_at in [
            ("Visible task", visible_account, self.user, self.team, None),
            ("Accountless task", None, self.user, self.team, None),
            ("Denied task", visible_account, self.user, self.team, None),
            ("Creator task", None, viewer, self.team, None),
            ("Hidden account task", hidden_account, self.user, self.team, None),
            ("Creator hidden account task", hidden_account, viewer, self.team, None),
            ("Other team task", None, viewer, other_team, None),
            ("Archived task", None, viewer, self.team, timezone.now()),
        ]:
            task = CustomerTask.objects.for_team(team.id).create(
                team=team, name=name, account=account, created_by=creator, archived_at=archived_at
            )
            if name in {"Denied task", "Creator task"}:
                AccessControl.objects.create(
                    team=self.team,
                    resource="customer_task",
                    resource_id=str(task.id),
                    access_level="none",
                    organization_member=membership,
                )

        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(hidden_account.id),
            access_level="none",
            organization_member=membership,
        )

        rows = execute_hogql_query("SELECT name FROM system.customer_tasks", team=self.team, user=viewer).results
        assert {row[0] for row in rows} == {"Visible task", "Accountless task", "Creator task", "Archived task"}

        active_rows = execute_hogql_query(
            "SELECT name FROM system.customer_tasks WHERE archived_at IS NULL", team=self.team, user=viewer
        ).results
        tasks, count = api.list_customer_tasks(
            team_id=self.team.id,
            user_access_control=UserAccessControl(user=viewer, team=self.team),
            filters=contracts.CustomerTaskListFilters(),
            offset=0,
            limit=100,
        )
        assert (
            {row[0] for row in active_rows}
            == {task.name for task in tasks}
            == {
                "Visible task",
                "Accountless task",
                "Creator task",
            }
        )
        assert count == 3
