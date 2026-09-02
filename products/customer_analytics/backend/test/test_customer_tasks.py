from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from rest_framework import status

from products.customer_analytics.backend.models import CustomerTask, CustomerTaskActivity
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
        activities_response = self.client.get(f"{self.url}{task.id}/activities/")
        assert activities_response.status_code == status.HTTP_200_OK
        assert activities_response.json()["count"] == 1
        assert activities_response.json()["results"][0]["activity_type"] == "created"
        activity = CustomerTaskActivity.objects.unscoped().get(task=task)
        assert activity.activity_type == "created"

    def test_noop_status_completion_archive_and_restore_lifecycle(self) -> None:
        created = self.client.post(self.url, {"name": "Follow up"}, format="json")
        task_id = created.json()["id"]
        activity_count = CustomerTaskActivity.objects.unscoped().filter(task_id=task_id).count()

        noop = self.client.patch(f"{self.url}{task_id}/", {"name": "Follow up"}, format="json")
        assert noop.status_code == status.HTTP_200_OK
        assert CustomerTaskActivity.objects.unscoped().filter(task_id=task_id).count() == activity_count

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
