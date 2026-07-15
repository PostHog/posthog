from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.models import IdentityProviderConfig, OrganizationDomain


class TestBackfillIdentityProviderConfigSamlRelayState(BaseTest):
    def _create_domain(self, domain: str = "posthog.com") -> OrganizationDomain:
        return OrganizationDomain.objects.create(organization=self.organization, domain=domain)

    def _create_config(self) -> IdentityProviderConfig:
        return IdentityProviderConfig.objects.create(organization=self.organization)

    def test_backfills_config_linked_from_exactly_one_domain(self):
        domain = self._create_domain()
        config = self._create_config()
        domain.identity_provider_config = config
        domain.save()

        call_command("backfill_identity_provider_config_saml_relay_state")

        config.refresh_from_db()
        assert config.saml_relay_state == str(domain.id)

    @parameterized.expand(
        [
            ("no_linked_domain", 0),
            ("multiple_linked_domains", 2),
        ]
    )
    def test_leaves_saml_relay_state_null_when_link_is_ambiguous(self, _name: str, domain_count: int) -> None:
        config = self._create_config()
        for i in range(domain_count):
            domain = self._create_domain(domain=f"domain-{i}.com")
            domain.identity_provider_config = config
            domain.save()

        call_command("backfill_identity_provider_config_saml_relay_state")

        config.refresh_from_db()
        assert config.saml_relay_state is None

    def test_dry_run_does_not_write(self):
        domain = self._create_domain()
        config = self._create_config()
        domain.identity_provider_config = config
        domain.save()

        call_command("backfill_identity_provider_config_saml_relay_state", "--dry-run")

        config.refresh_from_db()
        assert config.saml_relay_state is None

    def test_does_not_overwrite_an_already_populated_value(self):
        domain = self._create_domain()
        config = self._create_config()
        domain.identity_provider_config = config
        domain.save()
        config.saml_relay_state = "some-other-value"
        config.save(update_fields=["saml_relay_state"])

        call_command("backfill_identity_provider_config_saml_relay_state")

        config.refresh_from_db()
        assert config.saml_relay_state == "some-other-value"
