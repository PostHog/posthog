import datetime
from typing import cast

import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.cloud_utils import is_cloud
from posthog.models import Action, Tag

# Testing enterprise properties of actions here (i.e., tagging).


@pytest.mark.ee
class TestActionApi(APIBaseTest):
    def test_create_action_update_delete_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )

        response = self.client.post(f"/api/projects/{self.team.id}/actions/", data={"name": "user signed up"})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["tags"] == []

        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{response.json()['id']}",
            data={"name": "user signed up", "tags": ["hello", "random"]},
        )
        assert response.status_code == status.HTTP_200_OK
        assert set(response.json()["tags"]) == {"hello", "random"}

        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{response.json()['id']}",
            data={"name": "user signed up", "tags": []},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["tags"] == []

    def test_create_action_with_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            data={
                "name": "user signed up",
                "tags": ["nightly", "is", "a", "good", "girl"],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert set(response.json()["tags"]) == {"nightly", "is", "a", "good", "girl"}

    def test_actions_does_not_nplus1(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )

        # Ensure the cloud check is cached to not affect the number of queries
        assert not is_cloud()

        tag = Tag.objects.create(name="tag", team=self.team)
        for i in range(20):
            action = Action.objects.create(team=self.team, name=f"action_{i}")
            action.tagged_items.create(tag=tag)

        # django_session + user + team  + look up if rate limit is enabled (cached after first lookup)
        # + organizationmembership + organization + action + taggeditem
        # + access control queries
        with self.assertNumQueries(34):
            response = self.client.get(f"/api/projects/{self.team.id}/actions")
        assert response.json()["results"][0]["tags"][0] == "tag"
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 20

    def test_actions_no_duplicate_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            data={"name": "user signed up", "tags": ["a", "b", "a"]},
        )

        self.assertListEqual(sorted(response.json()["tags"]), ["a", "b"])
