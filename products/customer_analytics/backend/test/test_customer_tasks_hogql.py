from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

from posthog.models import OrganizationMembership, Team, User
from posthog.models.organization import AvailableFeature

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.facade import api, contracts
from products.customer_analytics.backend.models import Account
from products.customer_analytics.backend.models.customer_task import CustomerTask
from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES


class TestCustomerTasksHogqlAccess(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @parameterized.expand(
        [
            ("resource_access", True, {"Visible task", "Accountless task", "Creator task"}),
            ("task_grants_without_account_access", False, {"Accountless task", "Creator task"}),
        ]
    )
    @patch("posthog.permissions.posthog_feature_flag_enabled", return_value=False)
    def test_task_visibility_matches_rest_listing(
        self,
        _name: str,
        has_customer_analytics_access: bool,
        expected_active_task_names: set[str],
        _feature_flag_enabled: object,
    ) -> None:
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
        task_access_levels = {"Denied task": "none", "Creator task": "none"}
        if not has_customer_analytics_access:
            AccessControl.objects.create(
                team=self.team,
                resource="customer_analytics",
                resource_id=None,
                access_level="none",
                organization_member=membership,
            )
            task_access_levels.update({"Accountless task": "editor", "Hidden account task": "editor"})

        for name, account, creator, team, archived_at in [
            (
                "Visible task",
                visible_account if has_customer_analytics_access else None,
                self.user,
                self.team,
                None,
            ),
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
            if name in task_access_levels:
                AccessControl.objects.create(
                    team=self.team,
                    resource="customer_task",
                    resource_id=str(task.id),
                    access_level=task_access_levels[name],
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
        assert {row[0] for row in rows} == expected_active_task_names | {"Archived task"}

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
        assert {row[0] for row in active_rows} == {task.name for task in tasks} == expected_active_task_names
        assert count == len(expected_active_task_names)

        materialization_database = Database.create_for(
            team=self.team,
            bypass_warehouse_access_control=True,
            allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES,
        )
        materialization_rows = execute_hogql_query(
            "SELECT name FROM system.customer_tasks",
            team=self.team,
            context=HogQLContext(team_id=self.team.id, database=materialization_database),
        ).results
        assert {row[0] for row in materialization_rows} == {
            "Visible task",
            "Accountless task",
            "Denied task",
            "Creator task",
            "Hidden account task",
            "Creator hidden account task",
            "Archived task",
        }
