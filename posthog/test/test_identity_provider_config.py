import pytest
from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError
from django.utils import timezone

from posthog.models import IdentityProviderConfig, LinkedIdentityProviderConfig, Organization, OrganizationDomain
from posthog.models.identity_provider_config import DomainScope

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

    def test_creating_domain_with_idp_config_creates_link(self):
        config = IdentityProviderConfig.objects.create(organization=self.organization)
        domain = self._create_domain(identity_provider_config=config)

        assert LinkedIdentityProviderConfig.objects.filter(
            organization_domain=domain, identity_provider_config=config
        ).exists()
        config.refresh_from_db()
        assert config.saml_relay_state == str(domain.pk)
        assert config.scim_slug == str(domain.pk)

    def test_updating_domain_idp_config_creates_link(self):
        domain = self._create_domain()
        config = IdentityProviderConfig.objects.create(organization=self.organization)
        domain.identity_provider_config = config
        domain.save()

        assert LinkedIdentityProviderConfig.objects.filter(
            organization_domain=domain, identity_provider_config=config
        ).exists()
        config.refresh_from_db()
        assert config.saml_relay_state == str(domain.pk)
        assert config.scim_slug == str(domain.pk)

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

    def test_deleting_domain_deletes_orphaned_config(self):
        domain = self._create_domain()
        config = self._create_linked_config(domain, saml_entity_id="entity-id")

        domain.delete()
        assert not IdentityProviderConfig.objects.filter(pk=config.pk).exists()

    def test_deleting_domain_keeps_config_linked_to_another_domain(self):
        domain = self._create_domain()
        other_domain = self._create_domain(domain="other.posthog.com")
        config = self._create_linked_config(domain, saml_entity_id="entity-id")
        other_domain.identity_provider_config = config
        other_domain.save()

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


class TestIdentityProviderConfigDomainScope(BaseTest):
    SAML_KWARGS = {
        "saml_entity_id": "entity-id",
        "saml_acs_url": "https://idp.example.com/acs",
        "saml_x509_cert": "cert-contents",
    }

    def _create_domain(self, domain: str = "posthog.com", **kwargs) -> OrganizationDomain:
        return OrganizationDomain.objects.create(organization=self.organization, domain=domain, **kwargs)

    def _create_config(self, **kwargs) -> IdentityProviderConfig:
        return IdentityProviderConfig.objects.create(organization=self.organization, **kwargs)

    def _create_config_with_identifiers(self, name: str, **kwargs) -> IdentityProviderConfig:
        # `OrganizationDomain.save()` backfills empty identifiers with the domain's id, which
        # collides across configs once a domain moves between them. Pre-set them so tests about
        # linking aren't derailed by that.
        return self._create_config(name=name, saml_relay_state=name, scim_slug=name, **kwargs)

    def test_unset_domain_scope_is_treated_as_selected(self):
        config = self._create_config()
        assert config.domain_scope is None
        assert config.effective_domain_scope == DomainScope.SELECTED
        assert not config.applies_to_all_domains

    def test_selected_scope_only_covers_linked_domains(self):
        config = self._create_config(domain_scope=DomainScope.SELECTED)
        linked = self._create_domain(identity_provider_config=config)
        unlinked = self._create_domain("other.posthog.com")

        assert list(config.organization_domains) == [linked]
        assert list(unlinked.identity_provider_configs) == []
        assert unlinked.idp_config._state.adding  # the empty in-memory fallback

    def test_unset_scope_only_covers_linked_domains(self):
        config = self._create_config()
        linked = self._create_domain(identity_provider_config=config)
        self._create_domain("other.posthog.com")

        assert list(config.organization_domains) == [linked]

    def test_all_scope_covers_every_domain_in_the_organization(self):
        config = self._create_config(domain_scope=DomainScope.ALL, **self.SAML_KWARGS)
        linked = self._create_domain(identity_provider_config=config)
        unlinked = self._create_domain("other.posthog.com")

        assert set(config.organization_domains) == {linked, unlinked}
        # The unlinked domain resolves to the config without any join-table row of its own.
        assert list(unlinked.identity_provider_configs) == [config]
        assert unlinked.idp_config == config
        assert unlinked.has_saml

    def test_all_scope_does_not_cover_another_organizations_domains(self):
        other_org = Organization.objects.create(name="Other")
        other_domain = OrganizationDomain.objects.create(organization=other_org, domain="other.example.com")
        config = self._create_config(domain_scope=DomainScope.ALL)

        assert other_domain not in set(config.organization_domains)
        assert list(other_domain.identity_provider_configs) == []

    def test_explicitly_linked_config_wins_over_org_wide_one(self):
        org_wide = self._create_config(domain_scope=DomainScope.ALL, name="org-wide")
        linked = self._create_config(name="linked")
        domain = self._create_domain(identity_provider_config=linked)

        assert list(domain.identity_provider_configs) == [linked, org_wide]
        assert domain.idp_config == linked

    def test_org_wide_config_is_not_duplicated_by_links_to_other_domains(self):
        config = self._create_config(domain_scope=DomainScope.ALL)
        self._create_domain("a.posthog.com", identity_provider_config=config)
        self._create_domain("b.posthog.com", identity_provider_config=config)
        unlinked = self._create_domain("c.posthog.com")

        assert list(unlinked.identity_provider_configs) == [config]

    def test_repointing_the_domain_fk_drops_the_stale_link(self):
        first = self._create_config_with_identifiers("first")
        second = self._create_config_with_identifiers("second")
        domain = self._create_domain(identity_provider_config=first)

        domain.identity_provider_config = second
        domain.save()

        assert list(
            LinkedIdentityProviderConfig.objects.filter(organization_domain=domain).values_list(
                "identity_provider_config_id", flat=True
            )
        ) == [second.pk]
        assert domain.idp_config == second
        assert list(first.organization_domains) == []

    def test_clearing_the_domain_fk_drops_the_link(self):
        config = self._create_config()
        domain = self._create_domain(identity_provider_config=config)

        domain.identity_provider_config = None
        domain.save()

        assert not LinkedIdentityProviderConfig.objects.filter(organization_domain=domain).exists()
        assert list(config.organization_domains) == []
        assert domain.idp_config._state.adding

    def test_deleting_domain_keeps_org_wide_config_while_other_domains_remain(self):
        config = self._create_config(domain_scope=DomainScope.ALL)
        domain = self._create_domain(identity_provider_config=config)
        self._create_domain("other.posthog.com")

        domain.delete()
        assert IdentityProviderConfig.objects.filter(pk=config.pk).exists()

    def test_deleting_the_last_domain_deletes_the_org_wide_config(self):
        config = self._create_config(domain_scope=DomainScope.ALL)
        domain = self._create_domain(identity_provider_config=config)

        domain.delete()
        assert not IdentityProviderConfig.objects.filter(pk=config.pk).exists()

    def test_saml_availability_resolves_through_the_join_table(self):
        config = self._create_config(**self.SAML_KWARGS)
        domain = self._create_domain(identity_provider_config=config)
        domain.verified_at = timezone.now()
        domain.save()
        self.organization.available_product_features = [{"key": "saml", "name": "saml"}]
        self.organization.save()

        assert OrganizationDomain.objects.get_is_saml_available_for_email("someone@posthog.com")

        LinkedIdentityProviderConfig.objects.filter(organization_domain=domain).delete()
        assert not OrganizationDomain.objects.get_is_saml_available_for_email("someone@posthog.com")

    def test_saml_availability_resolves_through_an_org_wide_config(self):
        self._create_config(domain_scope=DomainScope.ALL, **self.SAML_KWARGS)
        domain = self._create_domain()  # never linked to the config
        domain.verified_at = timezone.now()
        domain.save()
        self.organization.available_product_features = [{"key": "saml", "name": "saml"}]
        self.organization.save()

        assert OrganizationDomain.objects.get_is_saml_available_for_email("someone@posthog.com")

    def test_saml_availability_ignores_a_partially_configured_config(self):
        self._create_config(domain_scope=DomainScope.ALL, saml_entity_id="entity-id")  # no ACS URL or cert
        domain = self._create_domain()
        domain.verified_at = timezone.now()
        domain.save()
        self.organization.available_product_features = [{"key": "saml", "name": "saml"}]
        self.organization.save()

        assert not OrganizationDomain.objects.get_is_saml_available_for_email("someone@posthog.com")
