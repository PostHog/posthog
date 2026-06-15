from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock

from rest_framework import status

from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.gateway import DEFAULT_GATEWAY_SLUG, Gateway
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from products.ai_gateway.backend.api import GatewayManagementPermission


class TestGatewayAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Renaming the gateway requires project-admin access (TeamMemberStrictManagementPermission).
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/gateways/{suffix}"

    def _gateway(self, team: Team | None = None) -> Gateway:
        return Gateway.objects.for_team((team or self.team).id).get(slug=DEFAULT_GATEWAY_SLUG)

    def test_list_returns_the_teams_gateway(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = [g["slug"] for g in response.json()["results"]]
        self.assertEqual(slugs, [DEFAULT_GATEWAY_SLUG])

    def test_create_is_disabled(self):
        # One gateway per team — provisioning owns creation, the API can't add more.
        response = self.client.post(self._url(), {"slug": "posthog_code"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_is_disabled(self):
        gateway = self._gateway()
        response = self.client.delete(self._url(f"{gateway.id}/"))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(Gateway.objects.for_team(self.team.id).filter(pk=gateway.pk).exists())

    def test_rename_gateway(self):
        gateway = self._gateway()
        response = self.client.patch(self._url(f"{gateway.id}/"), {"slug": "renamed"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        gateway.refresh_from_db()
        self.assertEqual(gateway.slug, "renamed")

    def test_rename_strips_whitespace(self):
        gateway = self._gateway()
        response = self.client.patch(self._url(f"{gateway.id}/"), {"slug": "  wizard  "})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["slug"], "wizard")

    def test_rename_rejects_malformed_slug(self):
        gateway = self._gateway()
        response = self.client.patch(self._url(f"{gateway.id}/"), {"slug": "Not Valid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "slug")

    def test_rename_to_own_slug_allowed(self):
        gateway = self._gateway()
        response = self.client.patch(self._url(f"{gateway.id}/"), {"slug": DEFAULT_GATEWAY_SLUG})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

    def test_gateways_isolated_per_team(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._gateway(other_team)  # other team's auto-provisioned gateway
        self.client.patch(self._url(f"{self._gateway().id}/"), {"slug": "renamed_here"})

        response = self.client.get(f"/api/projects/{other_team.id}/gateways/")
        slugs = [g["slug"] for g in response.json()["results"]]
        self.assertEqual(slugs, [DEFAULT_GATEWAY_SLUG])

    def test_child_environment_shares_parent_gateway(self):
        child = Team.objects.create(organization=self.organization, name="child", parent_team=self.team)
        self.client.patch(self._url(f"{self._gateway().id}/"), {"slug": "shared"})

        response = self.client.get(f"/api/projects/{child.id}/gateways/")
        slugs = [g["slug"] for g in response.json()["results"]]
        self.assertEqual(slugs, ["shared"])

    def test_member_cannot_rename(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        gateway = self._gateway()
        response = self.client.patch(self._url(f"{gateway.id}/"), {"slug": "members_blocked"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_management_permission_authorizes_against_parent_not_child_env(self):
        # The gateway is parent-owned, but the URL team_id can be a child environment.
        # Authorization must resolve to the parent, else a child-env-only admin could
        # rename the parent's shared gateway. (Differing per-team levels need the
        # access-control feature, so assert the permission's resolution directly.)
        child = Team.objects.create(organization=self.organization, name="child", parent_team=self.team)
        permission = GatewayManagementPermission()
        levels = {self.team.id: OrganizationMembership.Level.MEMBER}

        view = MagicMock()
        view.team = child
        view.user_permissions.team.side_effect = lambda team: MagicMock(effective_membership_level=levels[team.id])

        # Member on the parent → write denied, even though the URL points at the child env.
        self.assertFalse(permission.has_permission(MagicMock(method="PATCH"), view))
        view.user_permissions.team.assert_called_with(self.team)  # resolved to parent, not child

        # Admin on the parent → write allowed.
        levels[self.team.id] = OrganizationMembership.Level.ADMIN
        self.assertTrue(permission.has_permission(MagicMock(method="PATCH"), view))

    def test_management_permission_rejects_token_scoped_to_child_only(self):
        # APIScopePermission checks a token's scoped_teams against the URL team, which
        # can be a child env. Gateways are parent-owned, so a token scoped only to the
        # child must not manage them — the owner re-check lives in this permission.
        child = Team.objects.create(organization=self.organization, name="child", parent_team=self.team)
        permission = GatewayManagementPermission()

        view = MagicMock()
        view.team = child
        view.user_permissions.team.return_value = MagicMock(
            effective_membership_level=OrganizationMembership.Level.ADMIN
        )

        authr = PersonalAPIKeyAuthentication()
        authr.personal_api_key = MagicMock()
        request = MagicMock(method="PATCH", successful_authenticator=authr)

        # Token confined to the child env → denied, even though the user is a parent admin.
        authr.personal_api_key.scoped_teams = [child.id]
        self.assertFalse(permission.has_permission(request, view))

        # Token scoped to the parent (the gateway's owner) → allowed.
        authr.personal_api_key.scoped_teams = [self.team.id]
        self.assertTrue(permission.has_permission(request, view))

        # Unscoped token → allowed, falls back to the membership check.
        authr.personal_api_key.scoped_teams = None
        self.assertTrue(permission.has_permission(request, view))
