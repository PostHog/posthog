from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Insight, Organization, Tag, Team
from posthog.models.tagged_item import TaggedItem

from products.dashboards.backend.models.dashboard import Dashboard


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


class TestBulkUpdateTags(APIBaseTest):
    def _bulk_update_url(self):
        return f"/api/projects/{self.team.id}/dashboards/bulk_update_tags/"

    def _create_dashboard_with_tags(self, name, tag_names):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name=name)
        for tag_name in tag_names:
            tag, _ = Tag.objects.get_or_create(name=tag_name, team_id=self.team.id)
            dashboard.tagged_items.create(tag_id=tag.id)
        return dashboard

    def test_add_action_appends_tags_to_existing(self):
        dashboard = self._create_dashboard_with_tags("dash", ["existing"])

        response = self.client.post(
            self._bulk_update_url(),
            {"ids": [dashboard.id], "action": "add", "tags": ["new"]},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["updated"]) == 1
        assert sorted(data["updated"][0]["tags"]) == ["existing", "new"]
        assert data["skipped"] == []

    def test_remove_action_removes_specific_tags(self):
        dashboard = self._create_dashboard_with_tags("dash", ["keep", "remove-me"])

        response = self.client.post(
            self._bulk_update_url(),
            {"ids": [dashboard.id], "action": "remove", "tags": ["remove-me"]},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["updated"][0]["tags"] == ["keep"]
        assert data["skipped"] == []

    def test_set_action_replaces_all_tags(self):
        dashboard = self._create_dashboard_with_tags("dash", ["old1", "old2"])

        response = self.client.post(
            self._bulk_update_url(),
            {"ids": [dashboard.id], "action": "set", "tags": ["brand-new"]},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["updated"][0]["tags"] == ["brand-new"]
        assert data["skipped"] == []

    def test_add_across_multiple_objects(self):
        d1 = self._create_dashboard_with_tags("d1", ["alpha"])
        d2 = self._create_dashboard_with_tags("d2", ["beta"])

        response = self.client.post(
            self._bulk_update_url(),
            {"ids": [d1.id, d2.id], "action": "add", "tags": ["shared"]},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        updated_by_id = {item["id"]: item["tags"] for item in data["updated"]}
        assert sorted(updated_by_id[d1.id]) == ["alpha", "shared"]
        assert sorted(updated_by_id[d2.id]) == ["beta", "shared"]

    def test_set_with_empty_tags_clears_all_tags(self):
        dashboard = self._create_dashboard_with_tags("dash", ["one", "two"])

        response = self.client.post(
            self._bulk_update_url(),
            {"ids": [dashboard.id], "action": "set", "tags": []},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["updated"][0]["tags"] == []

    def test_remove_tag_not_on_object_is_noop(self):
        dashboard = self._create_dashboard_with_tags("dash", ["existing"])

        response = self.client.post(
            self._bulk_update_url(),
            {"ids": [dashboard.id], "action": "remove", "tags": ["nonexistent"]},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["updated"][0]["tags"] == ["existing"]
        assert data["skipped"] == []

    # --- Validation errors ---

    @parameterized.expand(
        [
            ("missing_ids", {}),
            ("empty_ids_list", {"ids": []}),
        ]
    )
    def test_missing_ids_returns_400(self, _name, extra_data):
        payload = {"action": "add", "tags": ["t"], **extra_data}
        response = self.client.post(self._bulk_update_url(), payload, content_type="application/json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["type"] == "validation_error"
        assert response.json()["attr"] == "ids"

    @parameterized.expand(
        [
            ("none", None),
            ("unknown_string", "upsert"),
            ("empty_string", ""),
        ]
    )
    def test_invalid_action_returns_400(self, _name, action_value):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dash")
        payload = {"ids": [dashboard.id], "action": action_value, "tags": ["t"]}
        response = self.client.post(self._bulk_update_url(), payload, content_type="application/json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["type"] == "validation_error"
        assert response.json()["attr"] == "action"

    def test_tags_not_a_list_returns_400(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dash")
        payload = {"ids": [dashboard.id], "action": "set", "tags": "not-a-list"}
        response = self.client.post(self._bulk_update_url(), payload, content_type="application/json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["type"] == "validation_error"
        assert response.json()["attr"] == "tags"

    @parameterized.expand(
        [
            ("add_empty_tags", "add"),
            ("remove_empty_tags", "remove"),
        ]
    )
    def test_empty_tags_for_add_or_remove_returns_400(self, _name, action_value):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dash")
        payload = {"ids": [dashboard.id], "action": action_value, "tags": []}
        response = self.client.post(self._bulk_update_url(), payload, content_type="application/json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["type"] == "validation_error"
        assert response.json()["attr"] == "tags"

    def test_all_non_integer_ids_returns_400(self):
        payload = {"ids": ["not-an-id", "also-bad"], "action": "set", "tags": ["t"]}
        response = self.client.post(self._bulk_update_url(), payload, content_type="application/json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["type"] == "validation_error"
        assert "ids" in response.json()["attr"]

    def test_not_found_ids_included_in_errors_and_valid_ones_updated(self):
        dashboard = self._create_dashboard_with_tags("dash", ["existing"])
        missing_id = 999999

        response = self.client.post(
            self._bulk_update_url(),
            {"ids": [dashboard.id, missing_id], "action": "add", "tags": ["new"]},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["updated"]) == 1
        assert data["updated"][0]["id"] == dashboard.id
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["id"] == missing_id
        assert data["skipped"][0]["reason"] == "Not found"

    def test_tags_are_normalized_via_tagify(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dash")

        response = self.client.post(
            self._bulk_update_url(),
            {"ids": [dashboard.id], "action": "set", "tags": ["  UPPER  ", "Mixed Case"]},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert sorted(data["updated"][0]["tags"]) == ["mixed case", "upper"]

    def test_normalized_tags_are_deduplicated(self):
        dashboard = Dashboard.objects.create(team_id=self.team.id, name="dash")

        response = self.client.post(
            self._bulk_update_url(),
            {"ids": [dashboard.id], "action": "set", "tags": ["Tag", "tag", "TAG"]},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["updated"][0]["tags"] == ["tag"]

    def test_removing_last_usage_of_tag_deletes_tag_object(self):
        dashboard = self._create_dashboard_with_tags("dash", ["orphan-soon"])

        self.client.post(
            self._bulk_update_url(),
            {"ids": [dashboard.id], "action": "remove", "tags": ["orphan-soon"]},
            content_type="application/json",
        )

        assert not Tag.objects.filter(name="orphan-soon", team_id=self.team.id).exists()

    def test_tag_shared_by_other_objects_is_not_deleted_on_remove(self):
        d1 = self._create_dashboard_with_tags("d1", ["shared-tag"])
        d2 = self._create_dashboard_with_tags("d2", ["shared-tag"])

        self.client.post(
            self._bulk_update_url(),
            {"ids": [d1.id], "action": "remove", "tags": ["shared-tag"]},
            content_type="application/json",
        )

        assert Tag.objects.filter(name="shared-tag", team_id=self.team.id).exists()
        remaining = list(d2.tagged_items.select_related("tag").values_list("tag__name", flat=True))
        assert "shared-tag" in remaining

    def test_bulk_update_tags_works_on_insights(self):
        insight = Insight.objects.create(team_id=self.team.id, name="my insight")
        tag, _ = Tag.objects.get_or_create(name="existing", team_id=self.team.id)
        insight.tagged_items.create(tag_id=tag.id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/bulk_update_tags/",
            {"ids": [insight.id], "action": "add", "tags": ["new-insight-tag"]},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["updated"][0]["id"] == insight.id
        assert sorted(data["updated"][0]["tags"]) == ["existing", "new-insight-tag"]

    def test_cannot_update_tags_on_other_teams_objects(self):
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        other_dashboard = Dashboard.objects.create(team_id=other_team.id, name="other team dash")
        other_tag = Tag.objects.create(name="other-tag", team_id=other_team.id)
        other_dashboard.tagged_items.create(tag_id=other_tag.id)

        response = self.client.post(
            self._bulk_update_url(),
            {"ids": [other_dashboard.id], "action": "set", "tags": ["hacked"]},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["updated"] == []
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["reason"] == "Not found"
        other_dashboard.refresh_from_db()
        actual_tags = list(other_dashboard.tagged_items.values_list("tag__name", flat=True))
        assert actual_tags == ["other-tag"]

    def test_too_many_ids_returns_400(self):
        from posthog.api.tagged_item import BULK_UPDATE_TAGS_MAX_IDS

        ids = list(range(1, BULK_UPDATE_TAGS_MAX_IDS + 2))
        response = self.client.post(
            self._bulk_update_url(),
            {"ids": ids, "action": "set", "tags": ["t"]},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["type"] == "validation_error"
        assert response.json()["attr"] == "ids"
