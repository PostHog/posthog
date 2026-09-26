from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.models import AccountView


def account_view_content(*components: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {
                "type": "ph-markdown-notebook",
                "attrs": {"nodeId": "markdown-notebook-v2", "markdown": "\n\n".join(components)},
            }
        ],
    }


class TestAccountViews(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.endpoint = f"/api/projects/{self.team.id}/account_views/"
        self.viewer = User.objects.create_and_join(self.organization, "viewer@example.com", "testtest")
        membership = OrganizationMembership.objects.get(user=self.viewer, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            access_level="viewer",
            organization_member=membership,
        )

    def _create(self) -> dict:
        response = self.client.post(
            self.endpoint,
            {
                "name": "Account workspace",
                "content": account_view_content('<Usage nodeId="usage-one" title="Product usage" />'),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.json()["visibility"], "private")
        return response.json()

    def test_private_view_is_not_readable_or_editable_by_another_user(self) -> None:
        view = self._create()

        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.endpoint).json(), [])
        self.assertEqual(self.client.get(f"{self.endpoint}{view['id']}/").status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            self.client.patch(
                f"{self.endpoint}{view['id']}/",
                {"name": "Changed", "version": view["version"]},
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_patch_rejects_team_visibility(self) -> None:
        view = self._create()

        response = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"visibility": "team", "version": view["version"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertEqual(AccountView.objects.for_team(self.team.id).get(id=view["id"]).visibility, "private")

    def test_stale_update_does_not_overwrite_newer_content(self) -> None:
        view = self._create()
        first = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"name": "First save", "version": view["version"]},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.json())
        unchanged = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"version": first.json()["version"]},
            format="json",
        )
        self.assertEqual(unchanged.status_code, status.HTTP_200_OK, unchanged.json())
        self.assertEqual(unchanged.json()["version"], first.json()["version"])

        stale = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"name": "Stale save", "version": view["version"]},
            format="json",
        )

        self.assertEqual(stale.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(AccountView.objects.for_team(self.team.id).get(id=view["id"]).name, "First save")

    def test_invalid_content_is_not_persisted(self) -> None:
        response = self.client.post(
            self.endpoint,
            {
                "name": "Invalid",
                "content": account_view_content('<Usage nodeId="same" accountId="customer-1" />'),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(AccountView.objects.for_team(self.team.id).exists())

    def test_create_update_and_delete_are_audited_without_content(self) -> None:
        view = self._create()
        updated = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {
                "name": "Updated private view",
                "content": account_view_content('<Usage nodeId="usage-one" title="Renewal details" />'),
                "version": view["version"],
            },
            format="json",
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK, updated.json())
        deleted = self.client.delete(f"{self.endpoint}{view['id']}/?version={updated.json()['version']}")
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)

        activities = ActivityLog.objects.filter(scope="AccountView", item_id=view["id"]).order_by("created_at")
        self.assertEqual([activity.activity for activity in activities], ["created", "updated", "deleted"])
        for activity in activities:
            self.assertNotIn("Account workspace", str(activity.detail))
            self.assertNotIn("Updated private view", str(activity.detail))
            self.assertNotIn("Product usage", str(activity.detail))
            self.assertNotIn("Renewal details", str(activity.detail))
