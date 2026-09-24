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
        self.editor = User.objects.create_and_join(self.organization, "editor@example.com", "testtest")
        self._set_access(self.viewer, "viewer")
        self._set_access(self.editor, "editor")

    def _set_access(self, user: User, access_level: str) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            access_level=access_level,
            organization_member=membership,
        )

    def _create(self) -> dict:
        response = self.client.post(
            self.endpoint,
            {
                "name": "Account workspace",
                "content": account_view_content(
                    '<Usage nodeId="usage-one" title="Product usage" />',
                    '<Usage nodeId="usage-two" span={6} />',
                ),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        return response.json()

    def test_private_view_becomes_readable_after_team_publish(self) -> None:
        view = self._create()

        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.endpoint).json(), [])

        self.client.force_login(self.user)
        published = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"visibility": "team", "version": view["version"]},
            format="json",
        )
        self.assertEqual(published.status_code, status.HTTP_200_OK, published.json())

        self.client.force_login(self.viewer)
        listed = self.client.get(self.endpoint)
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json())
        self.assertEqual([item["id"] for item in listed.json()], [view["id"]])
        self.assertFalse(listed.json()[0]["can_edit"])

    def test_team_editor_can_edit_but_cannot_delete_or_change_visibility(self) -> None:
        view = self._create()
        published = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"visibility": "team", "version": view["version"]},
            format="json",
        ).json()

        self.client.force_login(self.editor)
        updated = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"name": "Renewal workspace", "version": published["version"]},
            format="json",
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK, updated.json())
        self.assertEqual(updated.json()["name"], "Renewal workspace")
        self.assertFalse(updated.json()["can_delete"])

        denied_visibility = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"visibility": "private", "version": updated.json()["version"]},
            format="json",
        )
        self.assertEqual(denied_visibility.status_code, status.HTTP_403_FORBIDDEN)

        denied_delete = self.client.delete(f"{self.endpoint}{view['id']}/?version={updated.json()['version']}")
        self.assertEqual(denied_delete.status_code, status.HTTP_403_FORBIDDEN)

    def test_stale_update_does_not_overwrite_newer_content(self) -> None:
        view = self._create()
        first = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"name": "First save", "version": view["version"]},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.json())

        stale = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"name": "Stale save", "version": view["version"]},
            format="json",
        )
        self.assertEqual(stale.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(AccountView.objects.for_team(self.team.id).get(id=view["id"]).name, "First save")

    def test_invalid_content_changes_no_state(self) -> None:
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

    def test_deleting_creator_removes_private_views_and_preserves_team_views(self) -> None:
        private_view = self._create()
        team_view = self._create()
        published = self.client.patch(
            f"{self.endpoint}{team_view['id']}/",
            {"visibility": "team", "version": team_view["version"]},
            format="json",
        )
        self.assertEqual(published.status_code, status.HTTP_200_OK, published.json())

        self.user.delete()

        self.assertFalse(AccountView.objects.unscoped().filter(id=private_view["id"]).exists())
        preserved = AccountView.objects.unscoped().get(id=team_view["id"])
        self.assertIsNone(preserved.created_by_id)

    def test_activity_log_masks_content(self) -> None:
        view = self._create()
        activity = ActivityLog.objects.filter(scope="AccountView", item_id=view["id"]).latest("created_at")
        self.assertEqual(activity.activity, "created")
        self.assertNotIn("usage-one", str(activity.detail))
