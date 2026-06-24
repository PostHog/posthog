from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import IdentityProviderConfig, Organization, OrganizationMembership


class TestIdentityProviderConfigAPI(APIBaseTest):
    def _make_admin(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _enable_features(self, *features: str) -> None:
        self.organization.available_product_features = [{"key": f, "name": f} for f in features]
        self.organization.save()

    # List & retrieve

    def test_member_can_list_configs(self):
        IdentityProviderConfig.objects.create(organization=self.organization, name="Okta")
        response = self.client.get("/api/organizations/@current/identity_provider_configs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["name"], "Okta")

    def test_cannot_retrieve_config_from_other_org(self):
        self._make_admin()
        other_org = Organization.objects.create(name="Other")
        other_config = IdentityProviderConfig.objects.create(organization=other_org, name="Other Okta")
        response = self.client.get(f"/api/organizations/@current/identity_provider_configs/{other_config.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # Create & permissions

    def test_admin_can_create_config(self):
        self._make_admin()
        response = self.client.post(
            "/api/organizations/@current/identity_provider_configs/",
            {"name": "Okta production", "saml_entity_id": "entity", "saml_acs_url": "https://idp.example.com/acs"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        config = IdentityProviderConfig.objects.get(id=response.json()["id"])
        self.assertEqual(config.organization, self.organization)
        self.assertEqual(config.saml_entity_id, "entity")

    def test_member_cannot_create_config(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.post(
            "/api/organizations/@current/identity_provider_configs/",
            {"name": "Okta"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # SAML

    def test_can_configure_saml(self):
        self._make_admin()
        config = IdentityProviderConfig.objects.create(organization=self.organization)
        response = self.client.patch(
            f"/api/organizations/@current/identity_provider_configs/{config.id}/",
            {
                "saml_entity_id": "entity-id",
                "saml_acs_url": "https://idp.example.com/acs",
                "saml_x509_cert": "cert",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["has_saml"])
        config.refresh_from_db()
        self.assertEqual(config.saml_entity_id, "entity-id")

    # SCIM

    def test_enable_scim_returns_token_once(self):
        self._make_admin()
        self._enable_features(AvailableFeature.SCIM)
        config = IdentityProviderConfig.objects.create(organization=self.organization)

        response = self.client.patch(
            f"/api/organizations/@current/identity_provider_configs/{config.id}/",
            {"scim_enabled": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["scim_enabled"])
        self.assertIsNotNone(response.json()["scim_bearer_token"])

        config.refresh_from_db()
        self.assertTrue(config.scim_enabled)
        self.assertIsNotNone(config.scim_bearer_token)

        # A subsequent read never returns the plaintext token
        read = self.client.get(f"/api/organizations/@current/identity_provider_configs/{config.id}")
        self.assertIsNone(read.json()["scim_bearer_token"])

    def test_cannot_enable_scim_without_feature(self):
        self._make_admin()
        config = IdentityProviderConfig.objects.create(organization=self.organization)
        response = self.client.patch(
            f"/api/organizations/@current/identity_provider_configs/{config.id}/",
            {"scim_enabled": True},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "scim_enabled")

    def test_regenerate_scim_token(self):
        self._make_admin()
        self._enable_features(AvailableFeature.SCIM)
        config = IdentityProviderConfig.objects.create(organization=self.organization)
        enable = self.client.patch(
            f"/api/organizations/@current/identity_provider_configs/{config.id}/",
            {"scim_enabled": True},
        )
        original_token = enable.json()["scim_bearer_token"]

        response = self.client.post(f"/api/organizations/@current/identity_provider_configs/{config.id}/scim/token")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["scim_enabled"])
        self.assertNotEqual(response.json()["scim_bearer_token"], original_token)

    def test_regenerate_scim_token_requires_scim_enabled(self):
        self._make_admin()
        self._enable_features(AvailableFeature.SCIM)
        config = IdentityProviderConfig.objects.create(organization=self.organization)
        response = self.client.post(f"/api/organizations/@current/identity_provider_configs/{config.id}/scim/token")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ID-JAG (XAA)

    def test_can_configure_id_jag(self):
        self._make_admin()
        self._enable_features(AvailableFeature.XAA_AUTHENTICATION)
        config = IdentityProviderConfig.objects.create(organization=self.organization)
        response = self.client.patch(
            f"/api/organizations/@current/identity_provider_configs/{config.id}/",
            {
                "id_jag_issuer_url": "https://example.com/",
                "id_jag_jwks_url": "https://example.com/keys.json",
                "id_jag_allowed_clients": ["client-a"],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id_jag_issuer_url"], "https://example.com")
        self.assertTrue(response.json()["has_id_jag"])

    def test_cannot_configure_id_jag_without_feature(self):
        self._make_admin()
        config = IdentityProviderConfig.objects.create(organization=self.organization)
        response = self.client.patch(
            f"/api/organizations/@current/identity_provider_configs/{config.id}/",
            {"id_jag_issuer_url": "https://example.com"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "id_jag_issuer_url")

    def test_id_jag_url_must_be_allowed(self):
        self._make_admin()
        self._enable_features(AvailableFeature.XAA_AUTHENTICATION)
        config = IdentityProviderConfig.objects.create(organization=self.organization)
        response = self.client.patch(
            f"/api/organizations/@current/identity_provider_configs/{config.id}/",
            {"id_jag_issuer_url": "http://169.254.169.254/latest/meta-data"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
