from importlib import import_module

from posthog.test.base import BaseTest

from django.apps import apps

from posthog.models import IdentityProviderConfig, LinkedIdentityProviderConfig, OrganizationDomain

migration = import_module("posthog.migrations.1288_backfill_linked_identity_provider_configs")


class TestLinkedIdentityProviderConfigBackfill(BaseTest):
    def test_backfills_existing_domain_config_links_and_skips_unlinked_domains(self) -> None:
        linked_config = IdentityProviderConfig.objects.create(organization=self.organization)
        orphan_config = IdentityProviderConfig.objects.create(organization=self.organization)
        linked_domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="linked.example.com",
            identity_provider_config=linked_config,
        )
        OrganizationDomain.objects.create(
            organization=self.organization,
            domain="unlinked.example.com",
        )

        migration.backfill_linked_identity_provider_configs(apps, None)

        assert list(
            LinkedIdentityProviderConfig.objects.values_list("organization_domain_id", "identity_provider_config_id")
        ) == [(linked_domain.id, linked_config.id)]
        assert not LinkedIdentityProviderConfig.objects.filter(identity_provider_config_id=orphan_config.id).exists()

    def test_backfill_is_safe_to_run_again(self) -> None:
        config = IdentityProviderConfig.objects.create(organization=self.organization)
        domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="linked.example.com",
            identity_provider_config=config,
        )

        migration.backfill_linked_identity_provider_configs(apps, None)
        migration.backfill_linked_identity_provider_configs(apps, None)

        assert (
            LinkedIdentityProviderConfig.objects.filter(
                organization_domain_id=domain.id, identity_provider_config_id=config.id
            ).count()
            == 1
        )
