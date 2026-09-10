from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import IdentityProviderConfig, OrganizationMembership
from posthog.models.activity_logging.activity_log import ActivityLog


class TestIdentityProviderConfigActivityLogging(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _create_config(self, name="Okta production"):
        response = self.client.post(
            "/api/organizations/@current/identity_provider_configs/",
            {"name": name},
        )
        self.assertEqual(response.status_code, 201)
        config = IdentityProviderConfig.objects.get(id=response.json()["id"])
        ActivityLog.objects.filter(
            organization_id=self.organization.id,
            scope="IdentityProviderConfig",
        ).delete()
        return config

    @parameterized.expand(
        [
            (
                "saml-entity-id",
                "saml_entity_id",
                "https://idp.example.com",
                "SAML entity ID",
                "https://idp.example.com",
            ),
            (
                "saml-acs-url",
                "saml_acs_url",
                "https://idp.example.com/acs",
                "SAML ACS URL",
                "https://idp.example.com/acs",
            ),
            ("saml-x509-cert", "saml_x509_cert", "MIID...cert", "SAML X.509 certificate", "masked"),
        ]
    )
    def test_identity_provider_config_update_activity_logging(
        self, name_prefix, field, value, expected_field_name, expected_logged_value
    ):
        config = self._create_config(f"{name_prefix} config")

        response = self.client.patch(
            f"/api/organizations/@current/identity_provider_configs/{config.id}/",
            {field: value},
        )
        self.assertEqual(response.status_code, 200)

        log = ActivityLog.objects.filter(
            organization_id=self.organization.id,
            scope="IdentityProviderConfig",
            activity="updated",
        ).first()

        assert log is not None
        assert log.detail is not None
        changes = log.detail.get("changes", [])
        field_change = next((c for c in changes if c["field"] == expected_field_name), None)
        assert field_change is not None, f"Expected change for '{expected_field_name}' not found in {changes}"
        self.assertEqual(field_change["after"], expected_logged_value)
