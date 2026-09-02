from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.models import Account, CustomerTask, CustomerTaskActivity
from products.customer_analytics.backend.presentation.views.customer_tasks import (
    CustomerTaskCreateSerializer,
    CustomerTaskUpdateSerializer,
)


class CustomerTaskSerializerTest(SimpleTestCase):
    def test_public_writes_reject_internal_properties_and_blank_names(self) -> None:
        create_serializer = CustomerTaskCreateSerializer(data={"name": "  "})
        assert not create_serializer.is_valid()
        assert create_serializer.errors["name"][0] == "Enter a task name."

        properties_serializer = CustomerTaskCreateSerializer(data={"name": "Task", "properties": {"source": "sync"}})
        assert not properties_serializer.is_valid()
        assert "properties" in properties_serializer.errors

        update_serializer = CustomerTaskUpdateSerializer(data={"properties": {"source": "sync"}}, partial=True)
        assert not update_serializer.is_valid()
        assert "properties" in update_serializer.errors


class CustomerTaskAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.url = f"/api/projects/{self.team.id}/customer_tasks/"
        self.flag_patcher = patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        self.flag_patcher.start()
        self.addCleanup(self.flag_patcher.stop)

    def test_accountless_create_omits_properties_and_records_activity(self) -> None:
        response = self.client.post(self.url, {"name": "Follow up", "description": None}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["account"] is None
        assert "properties" not in response.json()
        task = CustomerTask.objects.unscoped().get(id=response.json()["id"])
        activities_response = self.client.get(f"{self.url}{task.id}/activities/?limit=1&offset=0")
        assert activities_response.status_code == status.HTTP_200_OK
        assert activities_response.json()["count"] == 1
        assert activities_response.json()["results"][0]["activity_type"] == "created"
        activity = CustomerTaskActivity.objects.unscoped().get(task=task)
        assert activity.activity_type == "created"

    def test_noop_status_completion_archive_and_restore_lifecycle(self) -> None:
        created = self.client.post(self.url, {"name": "Follow up"}, format="json")
        task_id = created.json()["id"]
        activity_count = CustomerTaskActivity.objects.unscoped().filter(task_id=task_id).count()
        updated_at_before = CustomerTask.objects.unscoped().get(id=task_id).updated_at

        noop = self.client.patch(f"{self.url}{task_id}/", {"name": "Follow up"}, format="json")
        assert noop.status_code == status.HTTP_200_OK
        assert CustomerTaskActivity.objects.unscoped().filter(task_id=task_id).count() == activity_count
        assert CustomerTask.objects.unscoped().get(id=task_id).updated_at == updated_at_before

        empty = self.client.patch(f"{self.url}{task_id}/", {}, format="json")
        assert empty.status_code == status.HTTP_400_BAD_REQUEST
        assert empty.json()["detail"] == "Change at least one task field."
        completed = self.client.patch(f"{self.url}{task_id}/", {"status": "completed"}, format="json")
        assert completed.status_code == status.HTTP_200_OK
        assert completed.json()["completed_at"] is not None
        assert completed.json()["completed_by"]["id"] == self.user.id

        invalid_transition = self.client.patch(f"{self.url}{task_id}/", {"status": "canceled"}, format="json")
        assert invalid_transition.status_code == status.HTTP_400_BAD_REQUEST
        assert invalid_transition.json()["status"] == "This task can't move from completed to canceled."
        archived = self.client.post(f"{self.url}{task_id}/archive/", {}, format="json")
        activities_before_repeat = CustomerTaskActivity.objects.unscoped().filter(task_id=task_id).count()
        repeated_archive = self.client.post(f"{self.url}{task_id}/archive/", {}, format="json")
        assert repeated_archive.status_code == status.HTTP_200_OK
        assert CustomerTaskActivity.objects.unscoped().filter(task_id=task_id).count() == activities_before_repeat
        assert archived.status_code == status.HTTP_200_OK
        blocked = self.client.patch(f"{self.url}{task_id}/", {"name": "Changed"}, format="json")
        assert blocked.status_code == status.HTTP_409_CONFLICT
        assert blocked.json()["detail"] == "Restore this task before editing it."

        restored = self.client.post(f"{self.url}{task_id}/restore/", {}, format="json")
        assert restored.status_code == status.HTTP_200_OK
        assert restored.json()["archived_at"] is None
        reopened = self.client.patch(f"{self.url}{task_id}/", {"status": "open"}, format="json")
        assert reopened.status_code == status.HTTP_200_OK
        assert reopened.json()["completed_at"] is None
        canceled = self.client.patch(f"{self.url}{task_id}/", {"status": "canceled"}, format="json")
        assert canceled.status_code == status.HTTP_200_OK
        assert (
            self.client.patch(f"{self.url}{task_id}/", {"status": "open"}, format="json").status_code
            == status.HTTP_200_OK
        )

    def test_customer_tasks_do_not_expose_object_access_control_actions(self) -> None:
        created = self.client.post(self.url, {"name": "Restricted task"}, format="json")
        task_id = created.json()["id"]

        response = self.client.put(
            f"{self.url}{task_id}/access_controls/",
            {"organization_member": str(self.organization_membership.id), "access_level": "none"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_feature_flag_denies_customer_tasks(self) -> None:
        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=False):
            response = self.client.get(self.url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_scopes_allow_reads_and_require_write_for_mutations(self) -> None:
        created = self.client.post(self.url, {"name": "Scoped task"}, format="json")
        task_id = created.json()["id"]

        read_key = self.create_personal_api_key_with_scopes(["customer_task:read"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {read_key}")
        assert self.client.get(f"{self.url}{task_id}/").status_code == status.HTTP_200_OK
        assert (
            self.client.patch(f"{self.url}{task_id}/", {"name": "Denied"}, format="json").status_code
            == status.HTTP_403_FORBIDDEN
        )

        write_key = self.create_personal_api_key_with_scopes(["customer_task:write"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {write_key}")
        assert (
            self.client.patch(f"{self.url}{task_id}/", {"name": "Updated"}, format="json").status_code
            == status.HTTP_200_OK
        )

    def test_assignee_can_only_read_and_update_assigned_tasks_and_loses_access_on_reassignment(self) -> None:
        assignee = User.objects.create_and_join(self.organization, "assignee@example.com", "testpassword")
        other_assignee = User.objects.create_and_join(self.organization, "other-assignee@example.com", "testpassword")
        assignee_membership = OrganizationMembership.objects.get(user=assignee, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="customer_task",
            resource_id=None,
            access_level="none",
            organization_member=assignee_membership,
        )
        assigned = self.client.post(
            self.url,
            {"name": "Assigned", "assigned_to_id": assignee.id},
            format="json",
        )
        unassigned = self.client.post(self.url, {"name": "Unassigned"}, format="json")
        assigned_id = assigned.json()["id"]

        self.client.force_login(assignee)
        listed = self.client.get(self.url).json()
        assert [task["id"] for task in listed["results"]] == [assigned_id]
        assert self.client.get(f"{self.url}{unassigned.json()['id']}/").status_code == status.HTTP_404_NOT_FOUND
        assert (
            self.client.patch(f"{self.url}{assigned_id}/", {"name": "Changed"}, format="json").status_code
            == status.HTTP_200_OK
        )

        self.client.force_login(self.user)
        reassigned = self.client.patch(
            f"{self.url}{assigned_id}/",
            {"assigned_to_id": other_assignee.id},
            format="json",
        )
        assert reassigned.status_code == status.HTTP_200_OK
        self.client.force_login(assignee)
        assert self.client.get(f"{self.url}{assigned_id}/").status_code == status.HTTP_404_NOT_FOUND

    def test_assignee_cannot_cross_account_visibility(self) -> None:
        assignee = User.objects.create_and_join(self.organization, "account-assignee@example.com", "testpassword")
        account = Account.objects.unscoped().create(team=self.team, name="Hidden account")
        created = self.client.post(
            self.url,
            {"name": "Account task", "account_id": str(account.id), "assigned_to_id": assignee.id},
            format="json",
        )
        membership = OrganizationMembership.objects.get(user=assignee, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(account.id),
            access_level="none",
            organization_member=membership,
        )

        self.client.force_login(assignee)
        assert self.client.get(self.url).json()["results"] == []
        assert self.client.get(f"{self.url}{created.json()['id']}/").status_code == status.HTTP_404_NOT_FOUND

    def test_cross_team_tasks_are_not_listed(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        CustomerTask.objects.unscoped().create(team=other_team, name="Other team task")

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert all(task["name"] != "Other team task" for task in response.json()["results"])

    def test_archived_tasks_are_retrievable_but_not_active_or_editable(self) -> None:
        created = self.client.post(self.url, {"name": "Archived task"}, format="json")
        task_id = created.json()["id"]
        assert self.client.post(f"{self.url}{task_id}/archive/", {}, format="json").status_code == status.HTTP_200_OK

        assert self.client.get(f"{self.url}{task_id}/").status_code == status.HTTP_200_OK
        assert all(task["id"] != task_id for task in self.client.get(self.url).json()["results"])
        assert self.client.get(f"{self.url}?archive_state=archived").json()["results"][0]["id"] == task_id
        assert (
            self.client.patch(f"{self.url}{task_id}/", {"name": "No edit"}, format="json").status_code
            == status.HTTP_409_CONFLICT
        )

    def test_ordering_and_pagination_are_deterministic(self) -> None:
        for name in ("C task", "A task", "B task"):
            assert self.client.post(self.url, {"name": name}, format="json").status_code == status.HTTP_201_CREATED

        first = self.client.get(f"{self.url}?ordering=name&limit=2&offset=0").json()
        second = self.client.get(f"{self.url}?ordering=name&limit=2&offset=2").json()

        assert [task["name"] for task in first["results"]] == ["A task", "B task"]
        assert [task["name"] for task in second["results"]] == ["C task"]
        assert first["count"] == 3
        assert first["next"] is not None
        assert second["previous"] is not None

    def test_update_validates_the_final_account_and_assignee_together(self) -> None:
        assignee = User.objects.create_and_join(self.organization, "final-state@example.com", "testpassword")
        account = Account.objects.unscoped().create(team=self.team, name="Final-state account")
        membership = OrganizationMembership.objects.get(user=assignee, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(account.id),
            access_level="none",
            organization_member=membership,
        )
        created = self.client.post(self.url, {"name": "Final-state task"}, format="json")

        response = self.client.patch(
            f"{self.url}{created.json()['id']}/",
            {"account_id": str(account.id), "assigned_to_id": assignee.id},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["assigned_to_id"] == (
            "This person can't access the selected account. Choose another assignee or remove the account link."
        )
