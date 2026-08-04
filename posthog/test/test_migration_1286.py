from importlib import import_module

from posthog.test.base import BaseTest

from django.apps import apps
from django.utils import timezone

from posthog.models import IdentityProviderConfig, OrganizationDomain

migration = import_module("posthog.migrations.1286_cleanup_orphaned_identity_provider_configs")


class TestCleanupOrphanedIdentityProviderConfigs(BaseTest):
    def _backdate(self, config: IdentityProviderConfig) -> None:
        # created_at is auto_now_add, so it has to be rewritten with an update
        IdentityProviderConfig.objects.filter(pk=config.pk).update(
            created_at=timezone.now() - migration.UNLINKED_GRACE_PERIOD * 2
        )

    def test_migration_deletes_only_configs_without_domains(self):
        orphaned_config = IdentityProviderConfig.objects.create(organization=self.organization)
        linked_config = IdentityProviderConfig.objects.create(organization=self.organization)
        self._backdate(orphaned_config)
        self._backdate(linked_config)
        OrganizationDomain.objects.create(
            organization=self.organization,
            domain="linked.posthog.com",
            identity_provider_config=linked_config,
        )

        migration.delete_orphaned_identity_provider_configs(apps, None)

        assert not IdentityProviderConfig.objects.filter(pk=orphaned_config.pk).exists()
        assert IdentityProviderConfig.objects.filter(pk=linked_config.pk).exists()

    def test_migration_keeps_recently_created_unlinked_configs(self):
        # A config created via the standalone create endpoint may not be linked to a domain yet, since
        # the frontend links it in a follow-up request
        in_progress_config = IdentityProviderConfig.objects.create(organization=self.organization)

        migration.delete_orphaned_identity_provider_configs(apps, None)

        assert IdentityProviderConfig.objects.filter(pk=in_progress_config.pk).exists()
