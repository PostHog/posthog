import pytest
from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from posthog.models import (
    IdentityProviderConfig,
    IdentityProviderConfigDomain,
    IdentityProviderConfigKind,
    Organization,
    OrganizationDomain,
)

# Legacy `OrganizationDomain` columns that mirror fields on `IdentityProviderConfig`. Test-only:
# used to build underscore-prefixed kwargs and to guard the two models' field shapes against drift.
_LEGACY_IDP_FIELDS: tuple[str, ...] = (
    "saml_entity_id",
    "saml_acs_url",
    "saml_x509_cert",
    "scim_enabled",
    "scim_bearer_token",
    "id_jag_issuer_url",
    "id_jag_jwks_url",
    "id_jag_allowed_clients",
)


def _prefix_idp_kwargs(kwargs: dict) -> dict:
    # The domain's legacy IdP columns are underscore-prefixed Python attributes; map the public names.
    return {(f"_{k}" if k in _LEGACY_IDP_FIELDS else k): v for k, v in kwargs.items()}


class TestIdentityProviderConfig(BaseTest):
    def _create_domain(self, domain: str = "posthog.com", **kwargs) -> OrganizationDomain:
        return OrganizationDomain.objects.create(
            organization=self.organization, domain=domain, **_prefix_idp_kwargs(kwargs)
        )

    def _create_linked_config(self, domain: OrganizationDomain, **config_kwargs) -> IdentityProviderConfig:
        config = IdentityProviderConfig.objects.create(organization=self.organization, **config_kwargs)
        domain.identity_provider_config = config
        domain.save()
        return config

    def test_saving_legacy_idp_columns_does_not_create_or_link_config(self):
        # The domain<->config dual-write mirror has been removed: writing the legacy underscore
        # columns must no longer auto-create or link an IdentityProviderConfig.
        domain = self._create_domain(
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert-contents",
        )
        domain.refresh_from_db()
        assert domain.identity_provider_config is None
        assert IdentityProviderConfig.objects.count() == 0

    def test_updating_linked_config_does_not_touch_legacy_domain_columns(self):
        # The reverse mirror (config -> domain) has been removed: updating a linked config must
        # not touch the domain's legacy columns anymore.
        domain = self._create_domain()
        config = self._create_linked_config(domain, saml_entity_id="entity-id")

        config.saml_entity_id = "new-entity-id"
        config.save()

        domain.refresh_from_db()
        assert domain._saml_entity_id is None

    def test_synced_fields_match_between_models(self):
        # Guard against the two models drifting apart. The domain stores these as underscore-prefixed
        # columns (with the original db_column), the config stores them under the plain name.
        for field in _LEGACY_IDP_FIELDS:
            domain_field = OrganizationDomain._meta.get_field(f"_{field}")
            config_field = IdentityProviderConfig._meta.get_field(field)
            assert domain_field.__class__ == config_field.__class__, field
            assert getattr(domain_field, "max_length", None) == getattr(config_field, "max_length", None), field
            assert getattr(domain_field, "db_column", None) == field, field

    def test_deleting_domain_keeps_config(self):
        domain = self._create_domain()
        config = self._create_linked_config(domain, saml_entity_id="entity-id")

        domain.delete()
        assert IdentityProviderConfig.objects.filter(pk=config.pk).exists()

    def test_cross_org_config_link_fails_validation(self):
        other_org = Organization.objects.create(name="Other")
        other_config = IdentityProviderConfig.objects.create(organization=other_org)
        domain = self._create_domain()
        domain.identity_provider_config = other_config

        with pytest.raises(ValidationError) as exc_info:
            domain.full_clean()
        assert "identity_provider_config" in exc_info.value.message_dict

    def test_cross_org_config_link_fails_on_direct_save(self):
        # `clean()`/`full_clean()` aren't invoked by plain `.save()`/`.objects.create()`, so the
        # cross-org guard must also be enforced from `save()` itself.
        other_org = Organization.objects.create(name="Other")
        other_config = IdentityProviderConfig.objects.create(organization=other_org)
        domain = self._create_domain()
        domain.identity_provider_config = other_config

        with pytest.raises(ValidationError) as exc_info:
            domain.save()
        assert "identity_provider_config" in exc_info.value.message_dict

    def test_cross_org_config_link_fails_on_create(self):
        other_org = Organization.objects.create(name="Other")
        other_config = IdentityProviderConfig.objects.create(organization=other_org)

        with pytest.raises(ValidationError) as exc_info:
            OrganizationDomain.objects.create(
                organization=self.organization, domain="posthog.com", identity_provider_config=other_config
            )
        assert "identity_provider_config" in exc_info.value.message_dict

    def test_dangling_config_link_fails_validation(self):
        domain = self._create_domain()
        config = self._create_linked_config(domain)
        # Delete the row out from under the FK without nulling the link on the in-memory instance.
        IdentityProviderConfig.objects.filter(pk=config.pk).delete()

        with pytest.raises(ValidationError) as exc_info:
            domain.full_clean()
        assert "identity_provider_config" in exc_info.value.message_dict

    def test_deleting_config_nulls_domain_link(self):
        domain = self._create_domain()
        config = self._create_linked_config(domain)

        config.delete()
        domain.refresh_from_db()
        assert domain.identity_provider_config is None

    def test_has_saml_reads_from_linked_config_not_legacy_domain_columns(self):
        domain = self._create_domain()  # legacy columns stay empty throughout
        config = self._create_linked_config(
            domain,
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert-contents",
        )
        assert domain.has_saml

        config.saml_entity_id = None
        config.save()
        domain.refresh_from_db()
        assert not domain.has_saml

    def test_domain_without_config_has_no_idp_reads(self):
        domain = self._create_domain()
        assert domain.identity_provider_config is None
        assert not domain.has_saml
        assert not domain.has_scim
        assert not domain.has_id_jag

    def test_typed_mappings_allow_shared_and_feature_specific_configs(self):
        first_domain = self._create_domain("posthog.com")
        second_domain = self._create_domain("posthog.dev")
        saml_config = IdentityProviderConfig.objects.create(
            organization=self.organization,
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert",
        )
        xaa_config = IdentityProviderConfig.objects.create(
            organization=self.organization,
            id_jag_issuer_url="https://idp.example.com",
        )

        for domain in (first_domain, second_domain):
            IdentityProviderConfigDomain.objects.create(
                organization=self.organization,
                identity_provider_config=saml_config,
                organization_domain=domain,
                kind=IdentityProviderConfigKind.SAML,
            )
        IdentityProviderConfigDomain.objects.create(
            organization=self.organization,
            identity_provider_config=xaa_config,
            organization_domain=first_domain,
            kind=IdentityProviderConfigKind.ID_JAG,
        )

        first_domain.refresh_from_db()
        second_domain.refresh_from_db()
        assert first_domain.saml_config == saml_config
        assert first_domain.id_jag_config == xaa_config
        assert second_domain.saml_config == saml_config
        assert second_domain.id_jag_config is None

    def test_mapping_rejects_cross_organization_domain(self):
        other_org = Organization.objects.create(name="Other")
        other_domain = OrganizationDomain.objects.create(organization=other_org, domain="other.example.com")
        config = IdentityProviderConfig.objects.create(organization=self.organization)

        with pytest.raises(ValidationError) as exc_info:
            IdentityProviderConfigDomain.objects.create(
                organization=self.organization,
                identity_provider_config=config,
                organization_domain=other_domain,
                kind=IdentityProviderConfigKind.SAML,
            )
        assert "organization_domain" in exc_info.value.message_dict
