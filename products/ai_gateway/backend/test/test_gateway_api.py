from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock

from django.test import override_settings

from rest_framework import status

from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.gateway import DEFAULT_GATEWAY_SLUG, Gateway
from posthog.models.organization import OrganizationMembership
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_secret, hash_key_value
from posthog.storage.gateway_credential_cache import (
    credential_hash,
    gateway_credential_hypercache as hypercache,
    project_gateway_credential,
)

from products.ai_gateway.backend.api import GatewayManagementPermission


class TestGatewayAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Managing gateways requires project-admin access (TeamMemberStrictManagementPermission).
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/gateways/{suffix}"

    def _gateway(self, slug: str = DEFAULT_GATEWAY_SLUG) -> Gateway:
        return Gateway.objects.for_team(self.team.id).get(slug=slug)

    def _bind_key(self, gateway: Gateway, label: str = "key", team: Team | None = None) -> ProjectSecretAPIKey:
        return ProjectSecretAPIKey.objects.create(
            label=label,
            team=team or self.team,
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["llm_gateway:read"],
            gateway=gateway,
        )

    def _unbound_key(
        self, label: str = "unbound", scopes: list[str] | None = None, team: Team | None = None
    ) -> ProjectSecretAPIKey:
        return ProjectSecretAPIKey.objects.create(
            label=label,
            team=team or self.team,
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=["llm_gateway:read"] if scopes is None else scopes,
        )

    def test_list_includes_auto_provisioned_gateway(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = [g["slug"] for g in response.json()["results"]]
        self.assertEqual(slugs, [DEFAULT_GATEWAY_SLUG])

    def test_create_gateway(self):
        response = self.client.post(self._url(), {"slug": "posthog_code"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        body = response.json()
        self.assertEqual(body["slug"], "posthog_code")
        self.assertEqual(body["created_by"]["id"], self.user.id)
        self.assertTrue(Gateway.objects.for_team(self.team.id).filter(slug="posthog_code").exists())

    def test_create_strips_whitespace(self):
        response = self.client.post(self._url(), {"slug": "  wizard  "})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.json()["slug"], "wizard")

    def test_create_rejects_malformed_slug(self):
        response = self.client.post(self._url(), {"slug": "Not Valid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "slug")

    def test_create_rejects_duplicate_slug(self):
        self.client.post(self._url(), {"slug": "posthog_code"})
        response = self.client.post(self._url(), {"slug": "posthog_code"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "slug")
        self.assertIn("already exists", response.json()["detail"])

    def test_rename_gateway(self):
        gateway = Gateway.objects.for_team(self.team.id).get(slug=DEFAULT_GATEWAY_SLUG)
        response = self.client.patch(self._url(f"{gateway.id}/"), {"slug": "renamed"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        gateway.refresh_from_db()
        self.assertEqual(gateway.slug, "renamed")

    def test_rename_to_existing_slug_rejected(self):
        self.client.post(self._url(), {"slug": "taken"})
        gateway = Gateway.objects.for_team(self.team.id).get(slug=DEFAULT_GATEWAY_SLUG)
        response = self.client.patch(self._url(f"{gateway.id}/"), {"slug": "taken"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rename_to_own_slug_allowed(self):
        gateway = Gateway.objects.for_team(self.team.id).get(slug=DEFAULT_GATEWAY_SLUG)
        response = self.client.patch(self._url(f"{gateway.id}/"), {"slug": DEFAULT_GATEWAY_SLUG})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

    def test_delete_any_gateway_including_the_only_one(self):
        gateway = Gateway.objects.for_team(self.team.id).get(slug=DEFAULT_GATEWAY_SLUG)
        response = self.client.delete(self._url(f"{gateway.id}/"))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Gateway.objects.for_team(self.team.id).exists())

    def test_delete_gateway_with_bound_credential_returns_409(self):
        # The credential gateway FK is PROTECT, so a gateway can't be deleted while a
        # credential still routes through it — unassign first.
        self.client.post(self._url(), {"slug": "busy"})
        gateway = self._gateway("busy")
        self._bind_key(gateway, "still-here")
        response = self.client.delete(self._url(f"{gateway.id}/"))
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Gateway.objects.for_team(self.team.id).filter(slug="busy").exists())

    def test_gateways_isolated_per_team(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        Gateway.objects.for_team(other_team.id).get(slug=DEFAULT_GATEWAY_SLUG)  # auto-provisioned
        self.client.post(self._url(), {"slug": "only_on_this_team"})

        response = self.client.get(f"/api/projects/{other_team.id}/gateways/")
        slugs = [g["slug"] for g in response.json()["results"]]
        self.assertEqual(slugs, [DEFAULT_GATEWAY_SLUG])

    def test_child_environment_shares_parent_gateways(self):
        child = Team.objects.create(organization=self.organization, name="child", parent_team=self.team)
        self.client.post(self._url(), {"slug": "shared"})

        response = self.client.get(f"/api/projects/{child.id}/gateways/")
        slugs = sorted(g["slug"] for g in response.json()["results"])
        self.assertEqual(slugs, [DEFAULT_GATEWAY_SLUG, "shared"])

    def test_member_cannot_write(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.post(self._url(), {"slug": "members_blocked"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_management_permission_authorizes_against_parent_not_child_env(self):
        # The gateway is parent-owned, but the URL team_id can be a child environment.
        # Authorization must resolve to the parent, else a child-env-only admin could
        # manage the parent's shared gateway. (Differing per-team levels need the
        # access-control feature, so assert the permission's resolution directly.)
        child = Team.objects.create(organization=self.organization, name="child", parent_team=self.team)
        permission = GatewayManagementPermission()
        levels = {self.team.id: OrganizationMembership.Level.MEMBER}

        view = MagicMock()
        view.team = child
        view.user_permissions.team.side_effect = lambda team: MagicMock(effective_membership_level=levels[team.id])

        # Member on the parent → write denied, even though the URL points at the child env.
        self.assertFalse(permission.has_permission(MagicMock(method="DELETE"), view))
        view.user_permissions.team.assert_called_with(self.team)  # resolved to parent, not child

        # Admin on the parent → write allowed.
        levels[self.team.id] = OrganizationMembership.Level.ADMIN
        self.assertTrue(permission.has_permission(MagicMock(method="DELETE"), view))

    def test_management_permission_rejects_token_scoped_to_child_only(self):
        # APIScopePermission checks a token's scoped_teams against the URL team, which
        # can be a child env. Gateways are parent-owned, so a token scoped only to the
        # child must not manage them — the owner re-check lives in this permission.
        child = Team.objects.create(organization=self.organization, name="child", parent_team=self.team)
        permission = GatewayManagementPermission()

        view = MagicMock()
        view.team = child
        view.action = None
        view.user_permissions.team.return_value = MagicMock(
            effective_membership_level=OrganizationMembership.Level.ADMIN
        )

        authr = PersonalAPIKeyAuthentication()
        authr.personal_api_key = MagicMock()
        request = MagicMock(method="DELETE", successful_authenticator=authr)

        # Token confined to the child env → denied, even though the user is a parent admin.
        authr.personal_api_key.scoped_teams = [child.id]
        self.assertFalse(permission.has_permission(request, view))

        # Token scoped to the parent (the gateway's owner) → allowed.
        authr.personal_api_key.scoped_teams = [self.team.id]
        self.assertTrue(permission.has_permission(request, view))

        # Unscoped token → allowed, falls back to the membership check.
        authr.personal_api_key.scoped_teams = None
        self.assertTrue(permission.has_permission(request, view))

    def test_bound_credentials_count(self):
        gateway = self._gateway()
        self._bind_key(gateway, "a")
        self._bind_key(gateway, "b")
        response = self.client.get(self._url())
        row = next(g for g in response.json()["results"] if g["id"] == str(gateway.id))
        self.assertEqual(row["bound_credentials_count"], 2)

    def test_credentials_action_lists_bound_keys(self):
        gateway = self._gateway()
        key = self._bind_key(gateway, "reports-bot")
        response = self.client.get(self._url(f"{gateway.id}/credentials/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        body = response.json()
        self.assertEqual([k["id"] for k in body["project_secret_api_keys"]], [str(key.id)])
        self.assertEqual(body["project_secret_api_keys"][0]["label"], "reports-bot")
        self.assertEqual(body["oauth_applications"], [])

    def test_assignable_credentials_lists_unbound_scoped_keys(self):
        mine = self._unbound_key("mine")
        self._unbound_key("no-scope", scopes=["feature_flag:read"])  # excluded: wrong scope
        self._bind_key(self._gateway(), "already-bound")  # excluded: bound to a gateway
        other_team = Team.objects.create(organization=self.organization, name="other-project")
        self._unbound_key("other-project-key", team=other_team)  # excluded: another project's key

        response = self.client.get(self._url("assignable_credentials/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual([k["label"] for k in response.json()], ["mine"])
        self.assertEqual(response.json()[0]["id"], str(mine.id))

    def test_assign_credential_binds_unbound_key(self):
        gateway = self._gateway()
        key = self._unbound_key("mine")
        response = self.client.post(self._url(f"{gateway.id}/assign_credential/"), {"credential_id": str(key.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        key.refresh_from_db()
        self.assertEqual(key.gateway_id, gateway.id)

    def test_assign_credential_rejects_key_from_another_project(self):
        gateway = self._gateway()
        other_team = Team.objects.create(organization=self.organization, name="other-project")
        key = self._unbound_key("elsewhere", team=other_team)
        response = self.client.post(self._url(f"{gateway.id}/assign_credential/"), {"credential_id": str(key.id)})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        key.refresh_from_db()
        self.assertIsNone(key.gateway_id)

    def test_assign_credential_rejects_key_without_gateway_scope(self):
        gateway = self._gateway()
        key = self._unbound_key("no-scope", scopes=["feature_flag:read"])
        response = self.client.post(self._url(f"{gateway.id}/assign_credential/"), {"credential_id": str(key.id)})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_assign_credential(self):
        # Project secret keys are team-owned, so binding one is an admin operation.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        gateway = self._gateway()
        key = self._unbound_key("mine")
        response = self.client.post(self._url(f"{gateway.id}/assign_credential/"), {"credential_id": str(key.id)})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        key.refresh_from_db()
        self.assertIsNone(key.gateway_id)

    def test_unassign_credential_unbinds_key_from_gateway(self):
        gateway = self._gateway()
        key = self._bind_key(gateway, "remove-me")
        response = self.client.post(
            self._url(f"{gateway.id}/unassign_credential/"),
            {"credential_type": "project_secret_api_key", "credential_id": str(key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        key.refresh_from_db()
        self.assertIsNone(key.gateway_id)

    @override_settings(AI_GATEWAY_REDIS_URL="redis://localhost")
    def test_unassign_clears_credential_blob_synchronously(self):
        # The unassign action clears the now-unbound key's blob in-band, so it can't keep
        # authenticating during the post_save signal's async window.
        hypercache.cache_client.clear()
        gateway = self._gateway()
        key = self._bind_key(gateway, "to-remove")
        project_gateway_credential(key)
        cache_key = hypercache.get_cache_key(credential_hash(key))
        assert hypercache.cache_client.get(cache_key) is not None

        response = self.client.post(
            self._url(f"{gateway.id}/unassign_credential/"),
            {"credential_type": "project_secret_api_key", "credential_id": str(key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertIsNone(hypercache.cache_client.get(cache_key))

    def test_unassign_credential_rejects_key_bound_to_another_gateway(self):
        gateway = self._gateway()
        self.client.post(self._url(), {"slug": "other"})
        other_gateway = self._gateway("other")
        key = self._bind_key(other_gateway, "elsewhere")
        response = self.client.post(
            self._url(f"{gateway.id}/unassign_credential/"),
            {"credential_type": "project_secret_api_key", "credential_id": str(key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        key.refresh_from_db()
        self.assertEqual(key.gateway_id, other_gateway.id)

    def test_member_cannot_unassign_credential(self):
        gateway = self._gateway()
        key = self._bind_key(gateway, "bound")
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.post(
            self._url(f"{gateway.id}/unassign_credential/"),
            {"credential_type": "project_secret_api_key", "credential_id": str(key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        key.refresh_from_db()
        self.assertEqual(key.gateway_id, gateway.id)
