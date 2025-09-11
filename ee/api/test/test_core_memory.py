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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["text"], "Initial memory")
        self.assertEqual(response.json()["results"][0]["id"], str(self.core_memory.id))

    def test_retrieve_core_memory(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/core_memory/{self.core_memory.pk}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["text"], "Initial memory")
        self.assertEqual(response.json()["id"], str(self.core_memory.id))

    def test_create_core_memory(self):
        self.core_memory.delete()

        response = self.client.post(f"/api/environments/{self.team.pk}/core_memory", {"text": "New memory"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["text"], "New memory")

        created_memory = CoreMemory.objects.get(team=self.team, text="New memory")
        self.assertTrue(created_memory)
        self.assertEqual(created_memory.initial_text, "New memory")
        self.assertEqual(created_memory.scraping_status, "completed")

    def test_cannot_create_duplicate_core_memory(self):
        count = CoreMemory.objects.count()
        with transaction.atomic():
            response = self.client.post(f"/api/environments/{self.team.pk}/core_memory", {"text": "Initial memory"})
            self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(response.json()["detail"], "Core memory already exists for this environment.")
        self.assertEqual(CoreMemory.objects.count(), count)

    def test_patch_core_memory(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/core_memory/{self.core_memory.pk}", {"text": "Updated memory"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["text"], "Updated memory")
        self.core_memory.refresh_from_db()
        self.assertEqual(self.core_memory.text, "Updated memory")

    def test_patch_core_memory_id_is_immutable(self):
        pk = self.core_memory.pk
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/core_memory/{self.core_memory.pk}",
            {"text": "Updated memory", "id": uuid4()},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(pk))
        self.core_memory.refresh_from_db()
        self.assertEqual(self.core_memory.pk, pk)

    def test_patch_blank_memory(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/core_memory/{self.core_memory.pk}", {"text": ""}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["text"], "")

    def test_cannot_patch_null_memory(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/core_memory/{self.core_memory.pk}", {"text": None}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_blank_memory(self):
        self.core_memory.delete()
        response = self.client.post(f"/api/environments/{self.team.pk}/core_memory", {"text": ""})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["text"], "")

    def test_cannot_post_null_memory(self):
        self.core_memory.delete()
        response = self.client.post(f"/api/environments/{self.team.pk}/core_memory", {"text": None})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_retrieve_other_team_memory(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/core_memory/{self.other_core_memory.pk}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_update_other_team_memory(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/core_memory/{self.other_core_memory.pk}",
            {"text": "Trying to update other team's memory"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.other_core_memory.refresh_from_db()
        self.assertEqual(self.other_core_memory.text, "Other team memory")

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.core_memory.refresh_from_db()
        # Only text should be updated
        self.assertEqual(self.core_memory.text, "Valid update")
        self.assertEqual(self.core_memory.team, self.team)
        self.assertEqual(self.core_memory.initial_text, "")
        self.assertEqual(self.core_memory.scraping_status, CoreMemory.ScrapingStatus.COMPLETED)
