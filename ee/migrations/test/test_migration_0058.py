import importlib
from types import SimpleNamespace

from posthog.test.base import BaseTest

from django.apps import apps
from django.db import connection

from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User

from ee.models.scim_provisioned_user import SCIMProvisionedUser

migration_module = importlib.import_module("ee.migrations.0058_backfill_scim_provisioned_user_config")
backfill_scim_provisioned_user_config = migration_module.backfill_scim_provisioned_user_config

SCHEMA_EDITOR = SimpleNamespace(connection=connection)


class TestBackfillSCIMProvisionedUserConfig(BaseTest):
    def setUp(self):
        super().setUp()
        self.config = IdentityProviderConfig.objects.create(organization=self.organization, scim_enabled=True)
        self.domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="example.com",
            verified_at="2024-01-01T00:00:00Z",
            identity_provider_config=self.config,
        )
        self.provisioned_user = User.objects.create_user(
            email="provisioned@example.com", password=None, first_name="Provisioned"
        )

    def _create_record(self, user: User, domain: OrganizationDomain) -> SCIMProvisionedUser:
        return SCIMProvisionedUser.objects.create(
            user=user,
            organization_domain=domain,
            identity_provider=SCIMProvisionedUser.IdentityProvider.OKTA,
            username=user.email,
        )

    def test_backfills_the_config_linked_to_the_record_domain(self):
        record = self._create_record(self.provisioned_user, self.domain)

        backfill_scim_provisioned_user_config(apps, SCHEMA_EDITOR)

        record.refresh_from_db()
        assert record.identity_provider_config_id == self.config.id

    def test_leaves_a_second_record_for_the_same_config_on_its_domain_key(self):
        # Two domains sharing a config used to serve SCIM separately, so one user can hold a record
        # per domain. Claiming both for the config would break the unique constraint added in 0060.
        second_domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="partner.example.com",
            verified_at="2024-01-01T00:00:00Z",
            identity_provider_config=self.config,
        )
        first_record = self._create_record(self.provisioned_user, self.domain)
        second_record = self._create_record(self.provisioned_user, second_domain)

        backfill_scim_provisioned_user_config(apps, SCHEMA_EDITOR)

        first_record.refresh_from_db()
        second_record.refresh_from_db()
        assert [first_record.identity_provider_config_id, second_record.identity_provider_config_id] == [
            self.config.id,
            None,
        ]
