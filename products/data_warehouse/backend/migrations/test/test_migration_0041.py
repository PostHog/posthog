import uuid
import importlib

import pytest

from django.apps import apps

from products.data_warehouse.backend.models import ExternalDataSource

migration_module = importlib.import_module(
    "products.data_warehouse.backend.migrations.0041_migrate_stripe_job_inputs_to_auth_type"
)
migrate_stripe_job_inputs = migration_module.migrate_stripe_job_inputs
reverse_migrate_stripe_job_inputs = migration_module.reverse_migrate_stripe_job_inputs


@pytest.fixture
def stripe_source_factory(team):
    def _create(job_inputs):
        return ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs=job_inputs,
        )

    return _create


@pytest.mark.django_db
class TestMigrateStripeJobInputs:
    @pytest.mark.parametrize(
        "input_job_inputs, expected_job_inputs",
        [
            (
                {"stripe_secret_key": "rk_live_test123", "stripe_account_id": "acct_123"},
                {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_test123"},
                    "stripe_account_id": "acct_123",
                },
            ),
            (
                {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_existing"},
                    "stripe_account_id": "acct_456",
                },
                {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_existing"},
                    "stripe_account_id": "acct_456",
                },
            ),
        ],
        ids=["api_key_to_nested", "already_migrated_skipped"],
    )
    def test_forward_migration(self, input_job_inputs, expected_job_inputs, stripe_source_factory):
        source = stripe_source_factory(input_job_inputs)

        migrate_stripe_job_inputs(apps, None)

        source.refresh_from_db()
        assert source.job_inputs == expected_job_inputs

    @pytest.mark.parametrize(
        "input_job_inputs, expected_job_inputs",
        [
            (
                {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_test123"},
                    "stripe_account_id": "acct_123",
                },
                {"stripe_secret_key": "rk_live_test123", "stripe_account_id": "acct_123"},
            ),
        ],
        ids=["nested_api_key_to_flat"],
    )
    def test_reverse_migration(self, input_job_inputs, expected_job_inputs, stripe_source_factory):
        source = stripe_source_factory(input_job_inputs)

        reverse_migrate_stripe_job_inputs(apps, None)

        source.refresh_from_db()
        assert source.job_inputs == expected_job_inputs

    def test_non_stripe_sources_unaffected(self, team):
        github_source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Github",
            job_inputs={"personal_access_token": "ghp_test123"},
        )

        migrate_stripe_job_inputs(apps, None)

        github_source.refresh_from_db()
        assert github_source.job_inputs == {"personal_access_token": "ghp_test123"}
