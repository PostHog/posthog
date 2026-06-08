from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock

from rest_framework import status

from posthog.models.gateway import DEFAULT_GATEWAY_SLUG, Gateway
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

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

    def _bind_key(self, gateway: Gateway, label: str = "key") -> PersonalAPIKey:
        return PersonalAPIKey.objects.create(
            label=label,
            user=self.user,
            secure_value=hash_key_value(generate_random_token_personal()),
            scopes=["llm_gateway:read"],
            gateway=gateway,
        )

    def _unbound_key(
        self, label: str = "unbound", scopes: list[str] | None = None, user: User | None = None
    ) -> PersonalAPIKey:
        return PersonalAPIKey.objects.create(
            label=label,
            user=user or self.user,
            secure_value=hash_key_value(generate_random_token_personal()),
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
        self.assertEqual([k["id"] for k in body["personal_api_keys"]], [str(key.id)])
        self.assertEqual(body["personal_api_keys"][0]["label"], "reports-bot")
        self.assertEqual(body["oauth_applications"], [])

    def test_assignable_credentials_lists_only_own_unbound_scoped_keys(self):
        mine = self._unbound_key("mine")
        self._unbound_key("no-scope", scopes=["feature_flag:read"])  # excluded: wrong scope
        self._bind_key(self._gateway(), "already-bound")  # excluded: bound to a gateway
        other = User.objects.create_and_join(self.organization, "other@example.com", "pw")
        self._unbound_key("theirs", user=other)  # excluded: not the requesting user's

        response = self.client.get(self._url("assignable_credentials/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual([k["label"] for k in response.json()], ["mine"])
        self.assertEqual(response.json()[0]["id"], str(mine.id))

    def test_assign_credential_binds_own_unbound_key(self):
        gateway = self._gateway()
        key = self._unbound_key("mine")
        response = self.client.post(self._url(f"{gateway.id}/assign_credential/"), {"credential_id": str(key.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        key.refresh_from_db()
        self.assertEqual(key.gateway_id, gateway.id)

    def test_assign_credential_rejects_other_users_key(self):
        gateway = self._gateway()
        other = User.objects.create_and_join(self.organization, "other2@example.com", "pw")
        key = self._unbound_key("theirs", user=other)
        response = self.client.post(self._url(f"{gateway.id}/assign_credential/"), {"credential_id": str(key.id)})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        key.refresh_from_db()
        self.assertIsNone(key.gateway_id)

    def test_assign_credential_rejects_key_without_gateway_scope(self):
        gateway = self._gateway()
        key = self._unbound_key("no-scope", scopes=["feature_flag:read"])
        response = self.client.post(self._url(f"{gateway.id}/assign_credential/"), {"credential_id": str(key.id)})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_can_assign_own_key(self):
        # Assigning your own key only touches that key, so it's member-level.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        gateway = self._gateway()
        key = self._unbound_key("mine")
        response = self.client.post(self._url(f"{gateway.id}/assign_credential/"), {"credential_id": str(key.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        key.refresh_from_db()
        self.assertEqual(key.gateway_id, gateway.id)

    def test_unassign_credential_unbinds_key_from_gateway(self):
        gateway = self._gateway()
        key = self._bind_key(gateway, "remove-me")
        response = self.client.post(
            self._url(f"{gateway.id}/unassign_credential/"),
            {"credential_type": "personal_api_key", "credential_id": str(key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        key.refresh_from_db()
        self.assertIsNone(key.gateway_id)

    def test_unassign_credential_rejects_key_bound_to_another_gateway(self):
        gateway = self._gateway()
        self.client.post(self._url(), {"slug": "other"})
        other_gateway = self._gateway("other")
        key = self._bind_key(other_gateway, "elsewhere")
        response = self.client.post(
            self._url(f"{gateway.id}/unassign_credential/"),
            {"credential_type": "personal_api_key", "credential_id": str(key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        key.refresh_from_db()
        self.assertEqual(key.gateway_id, other_gateway.id)

    def test_member_can_unassign_own_key_but_not_another_members(self):
        gateway = self._gateway()
        own = self._bind_key(gateway, "mine")
        other = User.objects.create_and_join(self.organization, "other3@example.com", "pw")
        theirs = PersonalAPIKey.objects.create(
            label="theirs",
            user=other,
            secure_value=hash_key_value(generate_random_token_personal()),
            scopes=["llm_gateway:read"],
            gateway=gateway,
        )
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Own key → allowed.
        response = self.client.post(
            self._url(f"{gateway.id}/unassign_credential/"),
            {"credential_type": "personal_api_key", "credential_id": str(own.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        # Another member's key → forbidden for a non-admin.
        response = self.client.post(
            self._url(f"{gateway.id}/unassign_credential/"),
            {"credential_type": "personal_api_key", "credential_id": str(theirs.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        theirs.refresh_from_db()
        self.assertEqual(theirs.gateway_id, gateway.id)
