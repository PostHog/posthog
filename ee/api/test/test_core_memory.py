from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.db import transaction

from rest_framework import status

from posthog.models.team.team import Team

from ee.models.assistant import CoreMemory


class TestCoreMemoryAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(team=self.team, text="Initial memory")
        self.other_team = Team.objects.create(organization=self.organization, name="other team")
        self.other_core_memory = CoreMemory.objects.create(team=self.other_team, text="Other team memory")

    def test_list_core_memories(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/core_memory")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["text"] == "Initial memory"
        assert response.json()["results"][0]["id"] == str(self.core_memory.id)

    def test_retrieve_core_memory(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/core_memory/{self.core_memory.pk}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["text"] == "Initial memory"
        assert response.json()["id"] == str(self.core_memory.id)

    def test_create_core_memory(self):
        self.core_memory.delete()

        response = self.client.post(f"/api/environments/{self.team.pk}/core_memory", {"text": "New memory"})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["text"] == "New memory"

        created_memory = CoreMemory.objects.get(team=self.team, text="New memory")
        assert created_memory
        assert created_memory.initial_text == "New memory"
        assert created_memory.scraping_status == "completed"

    def test_cannot_create_duplicate_core_memory(self):
        count = CoreMemory.objects.count()
        with transaction.atomic():
            response = self.client.post(f"/api/environments/{self.team.pk}/core_memory", {"text": "Initial memory"})
            assert response.status_code == status.HTTP_409_CONFLICT
            assert response.json()["detail"] == "Core memory already exists for this environment."
        assert CoreMemory.objects.count() == count

    def test_patch_core_memory(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/core_memory/{self.core_memory.pk}", {"text": "Updated memory"}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["text"] == "Updated memory"
        self.core_memory.refresh_from_db()
        assert self.core_memory.text == "Updated memory"

    def test_patch_core_memory_id_is_immutable(self):
        pk = self.core_memory.pk
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/core_memory/{self.core_memory.pk}",
            {"text": "Updated memory", "id": uuid4()},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(pk)
        self.core_memory.refresh_from_db()
        assert self.core_memory.pk == pk

    def test_patch_blank_memory(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/core_memory/{self.core_memory.pk}", {"text": ""}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["text"] == ""

    def test_cannot_patch_null_memory(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/core_memory/{self.core_memory.pk}", {"text": None}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_post_blank_memory(self):
        self.core_memory.delete()
        response = self.client.post(f"/api/environments/{self.team.pk}/core_memory", {"text": ""})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["text"] == ""

    def test_cannot_post_null_memory(self):
        self.core_memory.delete()
        response = self.client.post(f"/api/environments/{self.team.pk}/core_memory", {"text": None})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_retrieve_other_team_memory(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/core_memory/{self.other_core_memory.pk}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_update_other_team_memory(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/core_memory/{self.other_core_memory.pk}",
            {"text": "Trying to update other team's memory"},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        self.other_core_memory.refresh_from_db()
        assert self.other_core_memory.text == "Other team memory"

    def test_cannot_edit_fields_except_text(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/core_memory/{self.core_memory.pk}",
            {
                "text": "Valid update",
                "team": self.other_team.pk,  # Attempting to change team
                "initial_text": "Trying to change initial text",
                "scraping_status": "completed",
            },
        )
        assert response.status_code == status.HTTP_200_OK
        self.core_memory.refresh_from_db()
        # Only text should be updated
        assert self.core_memory.text == "Valid update"
        assert self.core_memory.team == self.team
        assert self.core_memory.initial_text == ""
        assert self.core_memory.scraping_status == CoreMemory.ScrapingStatus.COMPLETED
