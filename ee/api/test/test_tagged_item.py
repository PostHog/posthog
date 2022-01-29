from typing import cast

import pytest
from django.utils import timezone
from rest_framework import status

from posthog.models import Dashboard
from posthog.models.tagged_item import EnterpriseTaggedItem
from posthog.test.base import APIBaseTest

# Since tagged items are field level objects, there is no standalone API for tagged_items. Getting and setting
# tag properties are already tested thoroughly in each model's respective viewset. Therefore this test only tests
# the business logic for only requests routed through the enterprise path.


class TestEnterpriseTaggedItemSerializerMixin(APIBaseTest):
    @pytest.mark.ee
    def test_get_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )

        dashboard = Dashboard.objects.create(team_id=self.team.id, name="private dashboard")
        EnterpriseTaggedItem.objects.create(content_object=dashboard, tag="random", team=self.team)

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
        EnterpriseTaggedItem.objects.create(content_object=dashboard, tag="a", team=self.team)
        EnterpriseTaggedItem.objects.create(content_object=dashboard, tag="b", team=self.team)

        self.assertEqual(EnterpriseTaggedItem.objects.all().count(), 2)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}",
            {"name": "Default", "pinned": "true", "tags": ["b", "c", "d", "e"]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["b", "c", "d", "e"])
        self.assertEqual(EnterpriseTaggedItem.objects.all().count(), 4)

    @pytest.mark.ee
    def test_create_and_update_object_with_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )

        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "Default", "pinned": "true"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["tags"], [])
        self.assertEqual(EnterpriseTaggedItem.objects.all().count(), 0)

        id = response.json()["id"]
        response = self.client.patch(f"/api/projects/{self.team.id}/dashboards/{id}", {"tags": ["b", "c", "d", "e"]})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["b", "c", "d", "e"])
        self.assertEqual(EnterpriseTaggedItem.objects.all().count(), 4)
