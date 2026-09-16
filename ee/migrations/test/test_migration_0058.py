import importlib

from posthog.test.base import BaseTest

from django.apps import apps as current_apps
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.fields import RenameField

from parameterized import parameterized

from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User

from ee.models.scim_provisioned_user import SCIMProvisionedUser

migration_module = importlib.import_module("ee.migrations.0058_backfill_scim_provisioned_user_config")
backfill_scim_provisioned_user_config = migration_module.backfill_scim_provisioned_user_config


class FakeSchemaEditor:
    class connection:
        alias = "default"


def apps_before_the_rename():
    # posthog.1316 renames the field, and the squashes leave this backfill free to run on either
    # side of it. The current state with that one rename undone is the other side.
    state = MigrationLoader(connection=None).project_state()
    RenameField("organizationdomain", "_identity_provider_config", "identity_provider_config").state_forwards(
        "posthog", state
    )
    return state.apps


class TestBackfillScimProvisionedUserConfig(BaseTest):
    def _domain(self, domain: str, config: IdentityProviderConfig) -> OrganizationDomain:
        return OrganizationDomain.objects.create(
            organization=self.organization, domain=domain, _identity_provider_config=config
        )

    def _record(self, user: User, domain: OrganizationDomain) -> SCIMProvisionedUser:
        return SCIMProvisionedUser.objects.create(
            user=user,
            organization_domain=domain,
            identity_provider=SCIMProvisionedUser.IdentityProvider.OKTA,
            username=user.email,
        )

    @parameterized.expand([("before_the_rename",), ("after_the_rename",)])
    def test_claims_records_keyed_on_a_domain(self, case):
        config = IdentityProviderConfig.objects.create(organization=self.organization, scim_enabled=True)
        first_domain = self._domain("one.example.com", config)
        second_domain = self._domain("two.example.com", config)

        claimable = self._record(self.user, first_domain)
        duplicate_user = User.objects.create_and_join(self.organization, "duplicate@example.com", None)
        oldest_of_the_duplicates = self._record(duplicate_user, first_domain)
        newest_of_the_duplicates = self._record(duplicate_user, second_domain)

        apps = apps_before_the_rename() if case == "before_the_rename" else current_apps
        backfill_scim_provisioned_user_config(apps, FakeSchemaEditor())

        for record in (claimable, oldest_of_the_duplicates, newest_of_the_duplicates):
            record.refresh_from_db()
        assert claimable.identity_provider_config_id == config.id
        assert oldest_of_the_duplicates.identity_provider_config_id == config.id
        assert newest_of_the_duplicates.identity_provider_config_id is None
