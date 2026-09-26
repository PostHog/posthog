from importlib import import_module

from posthog.test.base import BaseTest

from django.apps import apps
from django.db import connection

from parameterized import parameterized

from posthog.models import IdentityProviderConfig, LinkedIdentityProviderConfig, OrganizationDomain

from ee.models.scim_provisioned_user import SCIMProvisionedUser
from ee.models.scim_request_log import SCIMRequestLog


class TestSplitIdentityProviderConfigScopes(BaseTest):
    def test_splits_only_present_features_and_preserves_links_and_scim_records(self) -> None:
        domain = OrganizationDomain.objects.create(organization=self.organization, domain="example.com")
        source = IdentityProviderConfig.objects.create(
            organization=self.organization,
            name="Example IdP",
            domain_scope="selected",
            saml_entity_id="partial-saml",
            oidc_client_id="partial-oidc",
            oidc_credentials={"client_secret": "example-secret"},
            scim_bearer_token="hashed-token",
            id_jag_jwks_url="https://example.com/keys",
        )
        LinkedIdentityProviderConfig.objects.create(organization_domain=domain, identity_provider_config=source)
        record = SCIMProvisionedUser.objects.create(
            user=self.user,
            identity_provider_config=source,
            identity_provider="okta",
            username="example",
        )
        log = SCIMRequestLog.objects.create(
            identity_provider_config=source,
            request_method="GET",
            request_path="/scim/v2/example/Users",
            response_status=200,
        )
        empty = IdentityProviderConfig.objects.create(organization=self.organization)
        already_scoped = IdentityProviderConfig.objects.create(organization=self.organization, config_scope="saml")

        migration = import_module("ee.migrations.0064_split_identity_provider_config_scopes")
        migration.split_identity_provider_config_scopes(apps, connection.schema_editor())

        assert not IdentityProviderConfig.objects.filter(pk__in=[source.pk, empty.pk]).exists()
        assert IdentityProviderConfig.objects.filter(pk=already_scoped.pk).exists()
        configs = {
            config.config_scope: config
            for config in IdentityProviderConfig.objects.filter(organization=self.organization).exclude(
                pk=already_scoped.pk
            )
        }
        assert set(configs) == {"saml", "oidc", "scim", "xaa"}
        assert configs["saml"].saml_entity_id == "partial-saml"
        assert str(configs["saml"].saml_relay_state) == str(source.saml_relay_state)
        assert not configs["saml"].oidc_client_id
        assert configs["oidc"].oidc_client_id == "partial-oidc"
        assert configs["oidc"].oidc_credentials == {"client_secret": "example-secret"}
        assert configs["scim"].scim_bearer_token == "hashed-token"
        assert str(configs["scim"].scim_slug) == str(source.scim_slug)
        assert not configs["scim"].saml_entity_id
        assert configs["xaa"].id_jag_jwks_url == "https://example.com/keys"
        assert all(
            config.name == source.name and config.domain_scope == source.domain_scope for config in configs.values()
        )
        assert set(
            LinkedIdentityProviderConfig.objects.filter(organization_domain=domain).values_list(
                "identity_provider_config_id", flat=True
            )
        ) == {config.pk for config in configs.values()}
        record.refresh_from_db()
        log.refresh_from_db()
        assert record.identity_provider_config_id == configs["scim"].pk
        assert log.identity_provider_config_id == configs["scim"].pk

    def test_generated_identifiers_do_not_create_empty_scopes(self) -> None:
        source = IdentityProviderConfig.objects.create(
            organization=self.organization,
            saml_acs_url="https://example.com/acs",
        )

        migration = import_module("ee.migrations.0064_split_identity_provider_config_scopes")
        migration.split_identity_provider_config_scopes(apps, connection.schema_editor())

        assert not IdentityProviderConfig.objects.filter(pk=source.pk).exists()
        assert list(
            IdentityProviderConfig.objects.filter(organization=self.organization).values_list("config_scope", flat=True)
        ) == ["saml"]

    @parameterized.expand([("provisioned_user",), ("request_log",)])
    def test_disabled_scim_preserves_record_attribution(self, record_type: str) -> None:
        source = IdentityProviderConfig.objects.create(
            organization=self.organization,
            scim_enabled=False,
            scim_bearer_token=None,
        )
        record: SCIMProvisionedUser | SCIMRequestLog
        if record_type == "provisioned_user":
            record = SCIMProvisionedUser.objects.create(
                user=self.user,
                identity_provider_config=source,
                identity_provider="okta",
                username="example",
            )
        else:
            record = SCIMRequestLog.objects.create(
                identity_provider_config=source,
                request_method="GET",
                request_path="/scim/v2/example/Users",
                response_status=200,
            )

        migration = import_module("ee.migrations.0064_split_identity_provider_config_scopes")
        migration.split_identity_provider_config_scopes(apps, connection.schema_editor())

        assert not IdentityProviderConfig.objects.filter(pk=source.pk).exists()
        scoped = IdentityProviderConfig.objects.get(organization=self.organization, config_scope="scim")
        assert str(scoped.scim_slug) == str(source.scim_slug)
        assert scoped.scim_enabled is False
        assert scoped.scim_bearer_token is None
        record.refresh_from_db()
        assert record.identity_provider_config_id == scoped.pk
