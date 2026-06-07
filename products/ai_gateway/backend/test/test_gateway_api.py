from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.gateway import DEFAULT_GATEWAY_SLUG, Gateway
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value


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

    def test_bind_credential_reassigns_between_gateways(self):
        source = self._gateway()
        key = self._bind_key(source, "movable")
        self.client.post(self._url(), {"slug": "target"})
        target = self._gateway("target")

        response = self.client.post(
            self._url(f"{target.id}/bind_credential/"),
            {"credential_type": "personal_api_key", "credential_id": str(key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        key.refresh_from_db()
        self.assertEqual(key.gateway_id, target.id)
        self.assertEqual(response.json()["bound_credentials_count"], 1)

    def test_bind_credential_rejects_credential_not_bound_to_team(self):
        gateway = self._gateway()
        other_team = Team.objects.create(organization=self.organization, name="other")
        foreign_key = self._bind_key(Gateway.objects.for_team(other_team.id).get(slug=DEFAULT_GATEWAY_SLUG))

        response = self.client.post(
            self._url(f"{gateway.id}/bind_credential/"),
            {"credential_type": "personal_api_key", "credential_id": str(foreign_key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_bind_credential(self):
        gateway = self._gateway()
        key = self._bind_key(gateway)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.post(
            self._url(f"{gateway.id}/bind_credential/"),
            {"credential_type": "personal_api_key", "credential_id": str(key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
