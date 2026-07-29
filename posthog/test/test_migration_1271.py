from importlib import import_module

from posthog.test.base import BaseTest

from django.apps import apps

from posthog.models import IdentityProviderConfig, OrganizationDomain

migration = import_module("posthog.migrations.1271_cleanup_orphaned_identity_provider_configs")


class TestCleanupOrphanedIdentityProviderConfigs(BaseTest):
    def test_migration_deletes_only_configs_without_domains(self):
        orphaned_config = IdentityProviderConfig.objects.create(organization=self.organization)
        linked_config = IdentityProviderConfig.objects.create(organization=self.organization)
        OrganizationDomain.objects.create(
            organization=self.organization,
            domain="linked.posthog.com",
            identity_provider_config=linked_config,
        )

        migration.delete_orphaned_identity_provider_configs(apps, None)

        assert not IdentityProviderConfig.objects.filter(pk=orphaned_config.pk).exists()
        assert IdentityProviderConfig.objects.filter(pk=linked_config.pk).exists()
