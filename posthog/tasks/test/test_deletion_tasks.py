from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.person import Person, PersonDistinctId
from posthog.models.project import Project
from posthog.models.team import Team
from posthog.personhog_client.fake_client import fake_personhog_client
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


class TestDeleteProjectPersonsEndToEnd(BaseTest):
    @parameterized.expand(
        [
            ("via_orm", False),
            ("via_personhog", True),
        ]
    )
    @patch("posthog.email.is_email_available", return_value=False)
    def test_deletes_persons_and_distinct_ids_for_team(
        self, _name: str, personhog_enabled: bool, mock_email: Any
    ) -> None:
        team = Team.objects.create(organization=self.organization, name="Team to delete")
        other_team = Team.objects.create(organization=self.organization, name="Other team")

        p1 = Person.objects.create(team=team, distinct_ids=["a", "b"])
        p2 = Person.objects.create(team=team, distinct_ids=["c"])
        p_other = Person.objects.create(team=other_team, distinct_ids=["d"])

        with fake_personhog_client(gate_enabled=personhog_enabled) as fake:
            if personhog_enabled:
                fake.add_person(team_id=team.id, person_id=p1.pk, uuid=str(p1.uuid), distinct_ids=["a", "b"])
                fake.add_person(team_id=team.id, person_id=p2.pk, uuid=str(p2.uuid), distinct_ids=["c"])
                fake.add_person(team_id=other_team.id, person_id=p_other.pk, uuid=str(p_other.uuid), distinct_ids=["d"])

            delete_project_data_and_notify_task(
                team_ids=[team.id],
                project_id=None,
                user_id=self.user.id,
                project_name="Team to delete",
            )

            self.assertFalse(Team.objects.filter(id=team.id).exists())

            if personhog_enabled:
                # Fake client doesn't touch Django DB — verify the RPC was called correctly
                calls = fake.assert_called("delete_persons_batch_for_team")
                team_ids_called = {c.request.team_id for c in calls}
                self.assertIn(team.id, team_ids_called)
                self.assertNotIn(other_team.id, team_ids_called)
            else:
                self.assertEqual(Person.objects.filter(team_id=team.id).count(), 0)
                self.assertEqual(PersonDistinctId.objects.filter(team_id=team.id).count(), 0)

                self.assertTrue(Person.objects.filter(id=p_other.id).exists())
                self.assertEqual(PersonDistinctId.objects.filter(team_id=other_team.id).count(), 1)


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

    @patch("posthog.ph_client.is_cloud", return_value=True)
    @patch("posthog.ph_client.get_client")
    @patch("posthog.email.is_email_available", return_value=False)
    def test_fires_deletion_completed_event(self, mock_email: Any, mock_get_client: Any, mock_is_cloud: Any) -> None:
        org = Organization.objects.create(name="Org to delete")
        org.members.add(self.user)
        team = Team.objects.create(organization=org, name="Team in org")
        org_id = str(org.id)

        delete_organization_data_and_notify_task(
            team_ids=[team.id],
            organization_id=org_id,
            user_id=self.user.id,
            organization_name="Org to delete",
            project_names=["Team in org"],
        )

        ph_client = mock_get_client.return_value
        event_names = [call.kwargs.get("event") for call in ph_client.capture.call_args_list]
        self.assertIn("organization deletion completed", event_names)
        ph_client.shutdown.assert_called()

    @patch("posthog.email.is_email_available", return_value=False)
    def test_deletes_organization_with_data_warehouse_saved_query_and_node(self, mock_email: Any) -> None:
        """
        Verify that Node.saved_query doesn't block organization and team deletion.
        """
        from products.data_modeling.backend.models import DAG, Node
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

        dag = DAG.objects.create(team=team, name=f"posthog_{team.id}")

        # Create a Node referencing the saved query (this has PROTECT on saved_query)
        node = Node.objects.create(
            team=team,
            saved_query=saved_query,
            dag=dag,
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

    @patch("posthog.email.is_email_available", return_value=False)
    def test_deletes_organization_when_user_already_deleted(self, mock_email: Any) -> None:
        org = Organization.objects.create(name="Org to delete")
        org.members.add(self.user)
        team = Team.objects.create(organization=org, name="Team in org")
        org_id = str(org.id)
        team_id = team.id
        project_id = team.project_id
        user_id = self.user.id

        # Simulate the user deleting their account before the async task runs
        self.user.delete()

        delete_organization_data_and_notify_task(
            team_ids=[team_id],
            organization_id=org_id,
            user_id=user_id,
            organization_name="Org to delete",
            project_names=["Team in org"],
        )

        self.assertFalse(Organization.objects.filter(id=org_id).exists())
        self.assertFalse(Team.objects.filter(id=team_id).exists())
        self.assertFalse(Project.objects.filter(id=project_id).exists())

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
