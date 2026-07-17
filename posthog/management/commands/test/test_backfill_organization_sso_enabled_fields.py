from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.models import IdentityProviderConfig, Organization


class TestBackfillOrganizationSsoEnabledFields(BaseTest):
    @parameterized.expand(
        [
            (
                "fully_configured_saml_scim_and_id_jag",
                {
                    "saml_entity_id": "entity-id",
                    "saml_acs_url": "https://idp.example.com/acs",
                    "saml_x509_cert": "cert-contents",
                    "scim_enabled": True,
                    "id_jag_issuer_url": "https://idp.example.com",
                },
                True,
                True,
                True,
            ),
            (
                "partial_saml_missing_cert_is_not_enabled",
                {
                    "saml_entity_id": "entity-id",
                    "saml_acs_url": "https://idp.example.com/acs",
                    "saml_x509_cert": None,
                },
                False,
                False,
                False,
            ),
            (
                "scim_enabled_true_counts_even_without_bearer_token",
                {"scim_enabled": True, "scim_bearer_token": None},
                False,
                True,
                False,
            ),
            (
                "scim_disabled_is_not_enabled",
                {"scim_enabled": False, "scim_bearer_token": "hashed-token"},
                False,
                False,
                False,
            ),
            (
                "id_jag_issuer_url_set",
                {"id_jag_issuer_url": "https://idp.example.com"},
                False,
                False,
                True,
            ),
            (
                "no_config_at_all_stays_disabled",
                None,
                False,
                False,
                False,
            ),
        ]
    )
    def test_backfill_sets_org_flags_from_linked_config(
        self, _name, config_kwargs, expected_saml_enabled, expected_scim_enabled, expected_id_jag_enabled
    ):
        if config_kwargs is not None:
            IdentityProviderConfig.objects.create(organization=self.organization, **config_kwargs)

        call_command("backfill_organization_sso_enabled_fields")

        self.organization.refresh_from_db()
        assert self.organization.is_saml_enabled is expected_saml_enabled
        assert self.organization.is_scim_enabled is expected_scim_enabled
        assert self.organization.is_id_jag_enabled is expected_id_jag_enabled

    def test_multiple_configs_on_same_org_are_ored_together(self):
        # One config covers SAML, a second covers SCIM + ID-JAG - the org should end up
        # enabled for all three, not just whichever config the loop happens to see last.
        IdentityProviderConfig.objects.create(
            organization=self.organization,
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert-contents",
        )
        IdentityProviderConfig.objects.create(
            organization=self.organization,
            scim_enabled=True,
            id_jag_issuer_url="https://idp.example.com",
        )

        call_command("backfill_organization_sso_enabled_fields")

        self.organization.refresh_from_db()
        assert self.organization.is_saml_enabled is True
        assert self.organization.is_scim_enabled is True
        assert self.organization.is_id_jag_enabled is True

    def test_organizations_are_isolated(self):
        other_org = Organization.objects.create(name="Other")
        IdentityProviderConfig.objects.create(
            organization=self.organization,
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert-contents",
            scim_enabled=True,
            id_jag_issuer_url="https://idp.example.com",
        )

        call_command("backfill_organization_sso_enabled_fields")

        other_org.refresh_from_db()
        assert other_org.is_saml_enabled is False
        assert other_org.is_scim_enabled is False
        assert other_org.is_id_jag_enabled is False

    def test_dry_run_does_not_modify_db(self):
        IdentityProviderConfig.objects.create(organization=self.organization, scim_enabled=True)

        call_command("backfill_organization_sso_enabled_fields", "--dry-run")

        self.organization.refresh_from_db()
        assert self.organization.is_scim_enabled is False

    def test_summary_reports_accurate_counts(self):
        IdentityProviderConfig.objects.create(organization=self.organization, scim_enabled=True)
        other_org = Organization.objects.create(name="Other")
        IdentityProviderConfig.objects.create(organization=other_org)  # config exists but nothing is enabled

        out = StringIO()
        call_command("backfill_organization_sso_enabled_fields", stdout=out)

        assert "Updated 1 of 2 organizations" in out.getvalue()
