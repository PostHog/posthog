from typing import cast

import pytest
from django.utils import timezone
from rest_framework import status

from posthog.models import Dashboard, Tag
from posthog.models.tagged_item import TaggedItem
from posthog.test.base import APIBaseTest

# This serializer only tests the business logic of getting and setting of ee descriptions. It uses the dashboard model
# as an example, since model specific functionality is already tested in their models' respective serializer tests.


class TestEnterpriseTaggedItemSerializerMixin(APIBaseTest):
    @pytest.mark.ee
    def test_get_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )

        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="random", team_id=self.team.id)
        dashboard.tagged_items.create(tag_id=tag.id)

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["random"])

    @pytest.mark.ee
    def test_resolve_overlapping_tags_on_update(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )

        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        tag_a = Tag.objects.create(name="a", team_id=self.team.id)
        tag_b = Tag.objects.create(name="b", team_id=self.team.id)
        dashboard.tagged_items.create(tag_id=tag_a.id)
        dashboard.tagged_items.create(tag_id=tag_b.id)

        self.assertEqual(TaggedItem.objects.all().count(), 2)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {"name": "Default", "pinned": "true", "tags": ["b", "c", "d", "e"]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(sorted(response.json()["tags"]), ["b", "c", "d", "e"])
        self.assertEqual(TaggedItem.objects.all().count(), 4)

    @pytest.mark.ee
    def test_create_and_update_object_with_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )

        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "Default", "pinned": "true"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["tags"], [])
        self.assertEqual(TaggedItem.objects.all().count(), 0)

        id = response.json()["id"]
        response = self.client.patch(f"/api/projects/{self.team.id}/dashboards/{id}", {"tags": ["b", "c", "d", "e"]})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(sorted(response.json()["tags"]), ["b", "c", "d", "e"])
        self.assertEqual(TaggedItem.objects.all().count(), 4)

    def test_create_with_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/", {"name": "Default", "pinned": "true", "tags": ["nightly"]}
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["tags"], ["nightly"])
        self.assertEqual(TaggedItem.objects.all().count(), 1)

    def test_no_duplicate_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )
        dashboard = Dashboard.objects.create(team=self.team, name="Edit-restricted dashboard", created_by=self.user)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}", {"tags": ["a", "b", "a"]},
        )

        self.assertListEqual(sorted(response.json()["tags"]), ["a", "b"])
