import pytest
from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError
from django.core.management import call_command

from posthog.models import IdentityProviderConfig, Organization, OrganizationDomain
from posthog.models.identity_provider_config import (
    IDP_CONFIG_SYNCED_FIELDS,
    sync_domains_from_identity_provider_config,
    sync_identity_provider_config_from_domain,
)

from ee.api.scim.utils import disable_scim_for_domain, enable_scim_for_domain, regenerate_scim_token


def _prefix_idp_kwargs(kwargs: dict) -> dict:
    # The domain's IdP columns are underscore-prefixed Python attributes; map the public names.
    return {(f"_{k}" if k in IDP_CONFIG_SYNCED_FIELDS else k): v for k, v in kwargs.items()}


class TestIdentityProviderConfigSync(BaseTest):
    def _create_domain(self, domain: str = "posthog.com", **kwargs) -> OrganizationDomain:
        return OrganizationDomain.objects.create(
            organization=self.organization, domain=domain, **_prefix_idp_kwargs(kwargs)
        )

    def test_domain_without_idp_settings_does_not_create_config(self):
        domain = self._create_domain()
        assert domain.identity_provider_config is None
        assert IdentityProviderConfig.objects.count() == 0

    def test_saving_saml_settings_creates_and_links_config(self):
        domain = self._create_domain()
        domain._saml_entity_id = "entity-id"
        domain._saml_acs_url = "https://idp.example.com/acs"
        domain._saml_x509_cert = "cert-contents"
        domain.save()

        domain.refresh_from_db()
        config = domain.identity_provider_config
        assert config is not None
        assert config.organization == self.organization
        assert config.name == "posthog.com"
        assert config.saml_entity_id == "entity-id"
        assert config.saml_acs_url == "https://idp.example.com/acs"
        assert config.saml_x509_cert == "cert-contents"
        assert config.has_saml

    def test_updating_domain_updates_linked_config(self):
        domain = self._create_domain(
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert-contents",
        )
        config = domain.identity_provider_config
        assert config is not None

        domain._saml_entity_id = "new-entity-id"
        domain._id_jag_issuer_url = "https://issuer.example.com"
        domain.save()

        config.refresh_from_db()
        assert config.saml_entity_id == "new-entity-id"
        assert config.id_jag_issuer_url == "https://issuer.example.com"
        # Still only one config — updates don't create new rows
        assert IdentityProviderConfig.objects.count() == 1

    def test_clearing_idp_settings_clears_linked_config(self):
        domain = self._create_domain(
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert-contents",
        )
        domain._saml_entity_id = None
        domain._saml_acs_url = None
        domain._saml_x509_cert = None
        domain.save()

        config = domain.identity_provider_config
        assert config is not None
        config.refresh_from_db()
        assert not config.has_saml
        assert config.saml_entity_id is None

    def test_scim_utils_dual_write_to_config(self):
        domain = self._create_domain()

        enable_scim_for_domain(domain)
        domain.refresh_from_db()
        config = domain.identity_provider_config
        assert config is not None
        assert config.scim_enabled is True
        assert config.scim_bearer_token == domain._scim_bearer_token
        assert config.has_scim

        regenerate_scim_token(domain)
        config.refresh_from_db()
        assert config.scim_bearer_token == domain._scim_bearer_token

        disable_scim_for_domain(domain)
        config.refresh_from_db()
        assert config.scim_enabled is False

    def test_sync_is_idempotent(self):
        domain = self._create_domain(id_jag_issuer_url="https://issuer.example.com")
        assert sync_identity_provider_config_from_domain(domain) == "unchanged"
        assert IdentityProviderConfig.objects.count() == 1

    def test_synced_fields_match_between_models(self):
        # Guard against the two models drifting apart. The domain stores these as underscore-prefixed
        # columns (with the original db_column), the config stores them under the plain name.
        for field in IDP_CONFIG_SYNCED_FIELDS:
            domain_field = OrganizationDomain._meta.get_field(f"_{field}")
            config_field = IdentityProviderConfig._meta.get_field(field)
            assert domain_field.__class__ == config_field.__class__, field
            assert getattr(domain_field, "max_length", None) == getattr(config_field, "max_length", None), field
            assert getattr(domain_field, "db_column", None) == field, field

    def test_deleting_domain_keeps_config(self):
        domain = self._create_domain(id_jag_issuer_url="https://issuer.example.com")
        config_id = domain.identity_provider_config_id
        domain.delete()
        assert config_id is not None
        assert IdentityProviderConfig.objects.filter(pk=config_id).exists()

    def test_cross_org_config_link_is_rejected(self):
        other_org = Organization.objects.create(name="Other")
        other_config = IdentityProviderConfig.objects.create(organization=other_org, saml_entity_id="other-entity")
        domain = self._create_domain()
        domain.identity_provider_config = other_config

        with pytest.raises(ValueError, match="different organization"):
            domain.save()

        # The cross-org config's settings must remain untouched
        other_config.refresh_from_db()
        assert other_config.saml_entity_id == "other-entity"

    def test_cross_org_config_link_fails_validation(self):
        other_org = Organization.objects.create(name="Other")
        other_config = IdentityProviderConfig.objects.create(organization=other_org)
        domain = self._create_domain()
        domain.identity_provider_config = other_config

        with pytest.raises(ValidationError) as exc_info:
            domain.full_clean()
        assert "identity_provider_config" in exc_info.value.message_dict

    def test_dangling_config_link_fails_validation(self):
        domain = self._create_domain(id_jag_issuer_url="https://issuer.example.com")
        config_id = domain.identity_provider_config_id
        assert config_id is not None
        # Delete the row out from under the FK without nulling the link
        IdentityProviderConfig.objects.filter(pk=config_id).delete()

        with pytest.raises(ValidationError) as exc_info:
            domain.full_clean()
        assert "identity_provider_config" in exc_info.value.message_dict

    def test_deleting_config_nulls_domain_link(self):
        domain = self._create_domain(id_jag_issuer_url="https://issuer.example.com")
        assert domain.identity_provider_config is not None
        domain.identity_provider_config.delete()
        domain.refresh_from_db()
        assert domain.identity_provider_config is None

    def test_config_save_syncs_to_linked_domain(self):
        domain = self._create_domain(
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert-contents",
        )
        config = domain.identity_provider_config
        assert config is not None

        config.saml_entity_id = "new-entity-id"
        config.save()

        domain.refresh_from_db()
        assert domain._saml_entity_id == "new-entity-id"

    def test_config_save_with_no_linked_domains_is_noop(self):
        config = IdentityProviderConfig.objects.create(organization=self.organization, saml_entity_id="entity-id")
        assert sync_domains_from_identity_provider_config(config) == 0

    def test_linking_populated_config_to_new_domain_does_not_clobber(self):
        # A new domain linked to an already-populated config must adopt the config's values, not
        # blank the (potentially shared) config via the forward mirror.
        config = IdentityProviderConfig.objects.create(
            organization=self.organization,
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert",
            scim_enabled=True,
            scim_bearer_token="hashed",
        )
        domain = OrganizationDomain.objects.create(
            organization=self.organization, domain="new.example.com", identity_provider_config=config
        )

        config.refresh_from_db()
        assert config.saml_entity_id == "entity-id"
        assert config.scim_enabled is True
        assert config.scim_bearer_token == "hashed"
        # The new domain adopts the config's values (config is the source of truth for reads).
        assert domain.has_saml
        assert domain._saml_entity_id == "entity-id"

    def test_domain_save_does_not_clobber_config_written_directly(self):
        domain = self._create_domain(
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert-contents",
        )
        config = domain.identity_provider_config
        assert config is not None

        # Write via the config (the source of truth)
        config.saml_entity_id = "config-owned-entity"
        config.save()

        # An unrelated domain save must not revert the config to a stale value
        domain.refresh_from_db()
        domain.jit_provisioning_enabled = True
        domain.save()

        config.refresh_from_db()
        domain.refresh_from_db()
        assert config.saml_entity_id == "config-owned-entity"
        assert domain._saml_entity_id == "config-owned-entity"

    def test_has_saml_reads_from_config_not_domain_columns(self):
        domain = self._create_domain(
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert-contents",
        )
        config = domain.identity_provider_config
        assert config is not None
        assert domain.has_saml

        # Blank the domain's own columns without touching the config (bypass sync via queryset update)
        OrganizationDomain.objects.filter(pk=domain.pk).update(_saml_entity_id="", _saml_acs_url="", _saml_x509_cert="")
        domain.refresh_from_db()
        # Reads resolve from the config, which still has SAML
        assert domain.has_saml

        # Clearing the config flips the read
        config.saml_entity_id = None
        config.saml_acs_url = None
        config.saml_x509_cert = None
        config.save()
        domain.refresh_from_db()
        assert not domain.has_saml

    def test_domain_without_config_has_no_idp_reads(self):
        domain = self._create_domain()
        assert domain.identity_provider_config is None
        assert not domain.has_saml
        assert not domain.has_scim
        assert not domain.has_id_jag


class TestSyncIdentityProviderConfigsCommand(BaseTest):
    def _create_unsynced_domain(self, domain: str, **kwargs) -> OrganizationDomain:
        # Bypass `OrganizationDomain.save()` dual-write to simulate pre-existing rows
        instance = OrganizationDomain(organization=self.organization, domain=domain, **_prefix_idp_kwargs(kwargs))
        instance.save()
        OrganizationDomain.objects.filter(pk=instance.pk).update(identity_provider_config=None)
        IdentityProviderConfig.objects.all().delete()
        instance.refresh_from_db()
        return instance

    def test_command_backfills_configs(self):
        saml_domain = self._create_unsynced_domain(
            "saml.example.com",
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert-contents",
        )
        plain_domain = self._create_unsynced_domain("plain.example.com")

        call_command("sync_identity_provider_configs")

        saml_domain.refresh_from_db()
        plain_domain.refresh_from_db()
        assert saml_domain.identity_provider_config is not None
        assert saml_domain.identity_provider_config.saml_entity_id == "entity-id"
        assert plain_domain.identity_provider_config is None
        assert IdentityProviderConfig.objects.count() == 1

    def test_command_resyncs_drifted_configs(self):
        domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="saml.example.com",
            _id_jag_issuer_url="https://issuer.example.com",
        )
        config = domain.identity_provider_config
        assert config is not None
        # Simulate drift in the mirror
        IdentityProviderConfig.objects.filter(pk=config.pk).update(id_jag_issuer_url="https://stale.example.com")

        call_command("sync_identity_provider_configs")

        config.refresh_from_db()
        assert config.id_jag_issuer_url == "https://issuer.example.com"

    def test_command_dry_run_makes_no_changes(self):
        self._create_unsynced_domain(
            "saml.example.com",
            saml_entity_id="entity-id",
            saml_acs_url="https://idp.example.com/acs",
            saml_x509_cert="cert-contents",
        )

        call_command("sync_identity_provider_configs", "--dry-run")

        assert IdentityProviderConfig.objects.count() == 0

    def test_command_filters_by_organization(self):
        other_org = Organization.objects.create(name="Other")
        other_domain = OrganizationDomain.objects.create(
            organization=other_org, domain="other.example.com", _id_jag_issuer_url="https://issuer.example.com"
        )
        # `_create_unsynced_domain` wipes all configs, leaving both domains unsynced
        domain = self._create_unsynced_domain("mine.example.com", id_jag_issuer_url="https://issuer.example.com")

        call_command("sync_identity_provider_configs", f"--organization-id={self.organization.id}")

        domain.refresh_from_db()
        other_domain.refresh_from_db()
        assert domain.identity_provider_config is not None
        assert other_domain.identity_provider_config is None
        assert IdentityProviderConfig.objects.count() == 1
