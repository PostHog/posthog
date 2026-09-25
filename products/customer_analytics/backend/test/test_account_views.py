from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.models import Account, AccountView


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
        self.project_admin = User.objects.create_and_join(self.organization, "admin@example.com", "testtest")
        admin_membership = OrganizationMembership.objects.get(user=self.project_admin, organization=self.organization)
        admin_membership.level = OrganizationMembership.Level.ADMIN
        admin_membership.save(update_fields=["level"])
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

    def _create(self, name: str = "Account workspace") -> dict:
        response = self.client.post(
            self.endpoint,
            {
                "name": name,
                "content": account_view_content('<Usage nodeId="usage-one" title="Product usage" />'),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.json()["visibility"], "private")
        return response.json()

    def _publish(self, view: dict) -> dict:
        response = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"visibility": "team", "version": view["version"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        return response.json()

    def test_private_view_is_not_visible_to_other_users(self) -> None:
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

    def test_team_view_is_visible_to_viewers_and_editable_by_editors(self) -> None:
        view = self._publish(self._create())

        self.client.force_login(self.viewer)
        listed = self.client.get(self.endpoint)
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json())
        self.assertEqual([item["id"] for item in listed.json()], [view["id"]])
        self.assertFalse(listed.json()[0]["can_edit"])
        self.assertFalse(listed.json()[0]["can_delete"])

        self.client.force_login(self.editor)
        updated = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"name": "Renewal workspace", "version": view["version"]},
            format="json",
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK, updated.json())
        self.assertEqual(updated.json()["name"], "Renewal workspace")
        self.assertTrue(updated.json()["can_edit"])
        self.assertFalse(updated.json()["can_delete"])

    def test_only_creator_or_project_admin_can_change_team_visibility_or_delete(self) -> None:
        view = self._publish(self._create())

        self.client.force_login(self.editor)
        denied_visibility = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"visibility": "private", "version": view["version"]},
            format="json",
        )
        self.assertEqual(denied_visibility.status_code, status.HTTP_403_FORBIDDEN, denied_visibility.json())
        denied_delete = self.client.delete(f"{self.endpoint}{view['id']}/?version={view['version']}")
        self.assertEqual(denied_delete.status_code, status.HTTP_403_FORBIDDEN, denied_delete.json())

        self.client.force_login(self.user)
        deleted = self.client.delete(f"{self.endpoint}{view['id']}/?version={view['version']}")
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)

    def test_project_admin_can_change_visibility_and_delete_team_views(self) -> None:
        view = self._publish(self._create())

        self.client.force_login(self.project_admin)
        made_private = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {"visibility": "private", "version": view["version"]},
            format="json",
        )
        self.assertEqual(made_private.status_code, status.HTTP_200_OK, made_private.json())
        self.assertEqual(made_private.json()["visibility"], "private")
        self.assertTrue(made_private.json()["can_delete"])

        deleted = self.client.delete(f"{self.endpoint}{view['id']}/?version={made_private.json()['version']}")
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)

    def test_account_specific_editor_cannot_edit_team_views_but_can_edit_own_private_views(self) -> None:
        team_view = self._publish(self._create())
        account_editor = User.objects.create_and_join(self.organization, "account-editor@example.com", "testtest")
        membership = OrganizationMembership.objects.get(user=account_editor, organization=self.organization)
        account = Account.objects.for_team(self.team.id).create(team=self.team, name="Restricted account")
        AccessControl.objects.create(
            team=self.team,
            resource="customer_analytics",
            access_level="none",
            organization_member=membership,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(account.id),
            access_level="editor",
            organization_member=membership,
        )
        private_view = AccountView.objects.for_team(self.team.id).create(
            team=self.team,
            name="Private workspace",
            content=account_view_content('<Usage nodeId="private-usage" />'),
            created_by=account_editor,
            last_modified_by=account_editor,
        )

        self.client.force_login(account_editor)
        denied = self.client.patch(
            f"{self.endpoint}{team_view['id']}/",
            {"name": "Blocked edit", "version": team_view["version"]},
            format="json",
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN, denied.json())
        self.assertEqual(AccountView.objects.for_team(self.team.id).get(id=team_view["id"]).name, "Account workspace")

        updated_private = self.client.patch(
            f"{self.endpoint}{private_view.id}/",
            {"name": "Updated private workspace", "version": private_view.version},
            format="json",
        )
        self.assertEqual(updated_private.status_code, status.HTTP_200_OK, updated_private.json())
        self.assertTrue(updated_private.json()["can_edit"])

    def test_stale_update_returns_conflict_without_overwriting_newer_content(self) -> None:
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
        private_view = self._create("Private workspace")
        team_view = self._publish(self._create("Shared workspace"))

        self.user.delete()

        self.assertFalse(AccountView.objects.unscoped().filter(id=private_view["id"]).exists())
        preserved = AccountView.objects.unscoped().get(id=team_view["id"])
        self.assertIsNone(preserved.created_by_id)

    def test_activity_log_masks_title_name_and_content_for_team_views(self) -> None:
        view = self._publish(self._create("Sensitive workspace"))
        updated = self.client.patch(
            f"{self.endpoint}{view['id']}/",
            {
                "name": "Updated workspace",
                "content": account_view_content('<Usage nodeId="usage-one" title="Renewal details" />'),
                "version": view["version"],
            },
            format="json",
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK, updated.json())

        activities = ActivityLog.objects.filter(scope="AccountView", item_id=view["id"]).order_by("created_at")
        self.assertEqual([activity.activity for activity in activities], ["created", "updated", "updated"])
        for activity in activities:
            self.assertIsNone(activity.detail.get("name"))
            self.assertNotIn("Sensitive workspace", str(activity.detail))
            self.assertNotIn("Updated workspace", str(activity.detail))
            self.assertNotIn("Product usage", str(activity.detail))
            self.assertNotIn("Renewal details", str(activity.detail))
