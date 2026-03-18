from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Dashboard, Insight, Tag
from posthog.models.tagged_item import TaggedItem


class TestTaggedItemSerializerMixin(APIBaseTest):
    def test_get_tags_returns_list(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="random", team_id=self.team.id)
        dashboard.tagged_items.create(tag_id=tag.id)

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["random"])
        self.assertEqual(Tag.objects.all().count(), 1)

    def test_create_with_tags(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/",
            {"name": "Default", "pinned": "true", "tags": ["random", "hello"]},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(sorted(response.json()["tags"]), ["hello", "random"])
        self.assertEqual(Tag.objects.all().count(), 2)

    def test_update_tags(self):
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
        self.assertEqual(sorted(response.json()["tags"]), ["hello", "random"])
        self.assertEqual(Tag.objects.all().count(), 2)

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
        # Tags unchanged when not provided
        self.assertEqual(response.json()["tags"], ["random"])

    def test_empty_tags_clears_all_tags(self):
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
        self.assertEqual(Tag.objects.all().count(), 0)

    def test_can_list_tags(self) -> None:
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="dashboard tag", team_id=self.team.id)
        dashboard.tagged_items.create(tag_id=tag.id)

        insight = Insight.objects.create(team_id=self.team.id, name="empty insight")
        tag2 = Tag.objects.create(name="insight tag", team_id=self.team.id)
        insight.tagged_items.create(tag_id=tag2.id)

        response = self.client.get(f"/api/projects/{self.team.id}/tags")
        assert response.status_code == status.HTTP_200_OK
        assert sorted(response.json()) == ["dashboard tag", "insight tag"]
