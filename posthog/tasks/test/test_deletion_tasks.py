from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team import Team
from posthog.tasks.tasks import delete_organization_data_and_notify_task, delete_project_data_and_notify_task


class TestDeleteProjectDataAndNotifyTask(BaseTest):
    @patch("posthog.email.is_email_available", return_value=False)
    def test_deletes_team_and_data(self, mock_email: Any) -> None:
        team = Team.objects.create(organization=self.organization, name="Team to delete")
        team_id = team.id

        delete_project_data_and_notify_task(
            team_ids=[team_id],
            project_id=None,
            user_id=self.user.id,
            project_name="Team to delete",
        )

        self.assertFalse(Team.objects.filter(id=team_id).exists())

    @patch("posthog.email.is_email_available", return_value=False)
    def test_deletes_project_and_teams(self, mock_email: Any) -> None:
        project, team = Project.objects.create_with_team(
            organization=self.organization,
            initiating_user=self.user,
            name="Project to delete",
        )
        project_id = project.id
        team_id = team.id

        delete_project_data_and_notify_task(
            team_ids=[team_id],
            project_id=project_id,
            user_id=self.user.id,
            project_name="Project to delete",
        )

        self.assertFalse(Project.objects.filter(id=project_id).exists())
        self.assertFalse(Team.objects.filter(id=team_id).exists())

    @patch("posthog.tasks.email.send_project_deleted_email")
    @patch("posthog.email.is_email_available", return_value=True)
    def test_sends_email_when_available(self, mock_email_available: Any, mock_send_email: Any) -> None:
        team = Team.objects.create(organization=self.organization, name="Team to delete")
        team_id = team.id

        delete_project_data_and_notify_task(
            team_ids=[team_id],
            project_id=None,
            user_id=self.user.id,
            project_name="Team to delete",
        )

        mock_send_email.delay.assert_called_once_with(
            user_id=self.user.id,
            project_name="Team to delete",
        )


class TestDeleteOrganizationDataAndNotifyTask(BaseTest):
    @patch("posthog.email.is_email_available", return_value=False)
    def test_deletes_organization_and_teams(self, mock_email: Any) -> None:
        org = Organization.objects.create(name="Org to delete")
        org.members.add(self.user)
        team = Team.objects.create(organization=org, name="Team in org")
        org_id = str(org.id)
        team_id = team.id

        delete_organization_data_and_notify_task(
            team_ids=[team_id],
            organization_id=org_id,
            user_id=self.user.id,
            organization_name="Org to delete",
            project_names=["Team in org"],
        )

        self.assertFalse(Organization.objects.filter(id=org_id).exists())
        self.assertFalse(Team.objects.filter(id=team_id).exists())

    @patch("posthog.email.is_email_available", return_value=False)
    def test_deletes_organization_with_data_warehouse_saved_query_and_node(self, mock_email: Any) -> None:
        """
        Verify that Node.saved_query doesn't block organization and team deletion.
        """
        from products.data_modeling.backend.models import Node
        from products.data_warehouse.backend.models import DataWarehouseSavedQuery

        org = Organization.objects.create(name="Org to delete")
        org.members.add(self.user)
        team = Team.objects.create(organization=org, name="Team in org")
        org_id = str(org.id)
        team_id = team.id

        # Create a DataWarehouseSavedQuery (view definition)
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=team,
            name="test_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
        )

        # Create a Node referencing the saved query (this has PROTECT on saved_query)
        node = Node.objects.create(
            team=team,
            saved_query=saved_query,
            type="view",
        )

        delete_organization_data_and_notify_task(
            team_ids=[team_id],
            organization_id=org_id,
            user_id=self.user.id,
            organization_name="Org to delete",
            project_names=["Team in org"],
        )

        self.assertFalse(Organization.objects.filter(id=org_id).exists())
        self.assertFalse(Team.objects.filter(id=team_id).exists())
        self.assertFalse(DataWarehouseSavedQuery.objects.filter(id=saved_query.id).exists())
        self.assertFalse(Node.objects.filter(id=node.id).exists())

    @patch("posthog.tasks.email.send_organization_deleted_email")
    @patch("posthog.email.is_email_available", return_value=True)
    def test_sends_email_when_available(self, mock_email_available: Any, mock_send_email: Any) -> None:
        org = Organization.objects.create(name="Org to delete")
        org.members.add(self.user)
        team = Team.objects.create(organization=org, name="Team in org")
        org_id = str(org.id)
        team_id = team.id

        delete_organization_data_and_notify_task(
            team_ids=[team_id],
            organization_id=org_id,
            user_id=self.user.id,
            organization_name="Org to delete",
            project_names=["Team in org"],
        )

        mock_send_email.delay.assert_called_once_with(
            user_id=self.user.id,
            organization_name="Org to delete",
            project_names=["Team in org"],
        )
