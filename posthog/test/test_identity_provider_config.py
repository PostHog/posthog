import uuid

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import IdentityProviderConfig, LinkedIdentityProviderConfig, Organization, OrganizationDomain
from posthog.models.identity_provider_config import ConfigScope, DomainScope


class TestIdentityProviderConfig(BaseTest):
    SAML_CONFIG = {
        "saml_entity_id": "entity-id",
        "saml_acs_url": "https://idp.example.com/acs",
        "saml_x509_cert": "cert-contents",
    }

    def _create_domain(self, domain: str = "posthog.com") -> OrganizationDomain:
        return OrganizationDomain.objects.create(organization=self.organization, domain=domain)

    def _create_config(self, **kwargs: object) -> IdentityProviderConfig:
        return IdentityProviderConfig.objects.create(organization=self.organization, **kwargs)

    def _link(self, domain: OrganizationDomain, config: IdentityProviderConfig) -> None:
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=domain,
            identity_provider_config=config,
        )

    def test_creating_config_populates_uuid_identifiers(self) -> None:
        config = self._create_config()

        assert uuid.UUID(str(config.saml_relay_state))
        assert uuid.UUID(str(config.scim_slug))
        assert config.saml_relay_state != config.scim_slug

    def test_deprecated_domain_foreign_key_does_not_create_a_link(self) -> None:
        config = self._create_config(**self.SAML_CONFIG)
        domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="posthog.com",
            _identity_provider_config=config,
        )

        assert not LinkedIdentityProviderConfig.objects.filter(organization_domain=domain).exists()
        assert domain.saml_identity_provider_configs.first() is None

    def test_deleting_domain_does_not_delete_config(self) -> None:
        config = self._create_config()
        domain = self._create_domain()
        self._link(domain, config)

        domain.delete()

        assert IdentityProviderConfig.objects.filter(pk=config.pk).exists()

    @parameterized.expand([(None,), (DomainScope.SELECTED,)])
    def test_selected_scope_only_resolves_explicit_links(self, domain_scope: str | None) -> None:
        config = self._create_config(domain_scope=domain_scope)
        linked_domain = self._create_domain()
        unlinked_domain = self._create_domain("other.posthog.com")
        self._link(linked_domain, config)

        assert list(config.organization_domains) == [linked_domain]
        assert list(linked_domain.identity_provider_configs) == [config]
        assert list(unlinked_domain.identity_provider_configs) == []

    def test_all_scope_resolves_every_domain_in_the_organization(self) -> None:
        config = self._create_config(domain_scope=DomainScope.ALL, **self.SAML_CONFIG)
        first_domain = self._create_domain()
        second_domain = self._create_domain("other.posthog.com")
        other_organization = Organization.objects.create(name="Other")
        other_domain = OrganizationDomain.objects.create(organization=other_organization, domain="example.com")

        assert set(config.organization_domains) == {first_domain, second_domain}
        assert first_domain.saml_identity_provider_configs.first() == config
        assert second_domain.saml_identity_provider_configs.first() == config
        assert list(other_domain.identity_provider_configs) == []

    def test_config_scope_selects_the_matching_config(self) -> None:
        domain = self._create_domain()
        saml_config = self._create_config(config_scope=ConfigScope.SAML, **self.SAML_CONFIG)
        second_saml_config = self._create_config(config_scope=ConfigScope.SAML, **self.SAML_CONFIG)
        xaa_config = self._create_config(
            config_scope=ConfigScope.ID_JAG,
            id_jag_issuer_url="https://idp.example.com",
        )
        self._link(domain, saml_config)
        self._link(domain, second_saml_config)
        self._link(domain, xaa_config)

        assert list(domain.saml_identity_provider_configs) == [saml_config, second_saml_config]
        assert list(domain.identity_provider_configs_for_scope(ConfigScope.ID_JAG)) == [xaa_config]

    def test_explicit_config_takes_precedence_over_all_scope(self) -> None:
        organization_config = self._create_config(domain_scope=DomainScope.ALL, **self.SAML_CONFIG)
        selected_config = self._create_config(**self.SAML_CONFIG)
        domain = self._create_domain()
        self._link(domain, selected_config)

        assert list(domain.identity_provider_configs) == [selected_config, organization_config]
        assert domain.saml_identity_provider_configs.first() == selected_config

    def test_saml_availability_resolves_through_join_table(self) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.SAML, "name": "SAML"}]
        self.organization.save()
        config = self._create_config(**self.SAML_CONFIG)
        domain = self._create_domain()
        domain._complete_verification()
        self._link(domain, config)

        assert IdentityProviderConfig.objects.get_is_saml_available_for_email("person@posthog.com")

        LinkedIdentityProviderConfig.objects.filter(organization_domain=domain).delete()
        assert not IdentityProviderConfig.objects.get_is_saml_available_for_email("person@posthog.com")
