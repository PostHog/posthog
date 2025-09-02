from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Dashboard, Insight, Tag
from posthog.models.tagged_item import TaggedItem

# This serializer only tests that enterprise functionality is not exposed on non-ee requests. It uses the dashboard
# model as an example, since model specific functionality is already tested in their models' respective serializer
# tests.


class TestTaggedItemSerializerMixin(APIBaseTest):
    def test_get_tags_on_non_ee_returns_empty_list(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="random", team_id=self.team.id)
        dashboard.tagged_items.create(tag_id=tag.id)

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], [])
        self.assertEqual(Tag.objects.all().count(), 1)

    def test_create_tags_on_non_ee_not_allowed(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/",
            {"name": "Default", "pinned": "true", "tags": ["random", "hello"]},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["tags"], [])
        self.assertEqual(Tag.objects.all().count(), 0)

    def test_update_tags_on_non_ee_not_allowed(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="random", team_id=self.team.id)
        dashboard.tagged_items.create(tag_id=tag.id)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {
                "name": "dashboard new name",
                "creation_mode": "duplicate",
                "tags": ["random", "hello"],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], [])
        self.assertEqual(Tag.objects.all().count(), 1)

    def test_undefined_tags_allows_other_props_to_update(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="random", team_id=self.team.id)
        dashboard.tagged_items.create(tag_id=tag.id)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {
                "name": "dashboard new name",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "dashboard new name")

    def test_empty_tags_does_not_delete_tags(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="random", team_id=self.team.id)
        dashboard.tagged_items.create(tag_id=tag.id)

        self.assertEqual(TaggedItem.objects.all().count(), 1)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {"name": "dashboard new name", "tags": []},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], [])
        self.assertEqual(Tag.objects.all().count(), 1)

    def test_can_list_tags_on_non_ee_and_get_empty_list(self) -> None:
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="dashboard tag", team_id=self.team.id)
        dashboard.tagged_items.create(tag_id=tag.id)

        insight = Insight.objects.create(team_id=self.team.id, name="empty insight")
        tag = Tag.objects.create(name="insight tag", team_id=self.team.id)
        insight.tagged_items.create(tag_id=tag.id)

        response = self.client.get(f"/api/projects/{self.team.id}/tags")
        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert response.json() == []
