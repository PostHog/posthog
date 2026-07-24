import uuid
import importlib

import pytest

from django.apps import apps

from products.warehouse_sources.backend.facade.models import ExternalDataSource

migration_module = importlib.import_module(
    "products.data_warehouse.backend.migrations.0058_set_default_stripe_api_version"
)
set_default_stripe_api_version = migration_module.set_default_stripe_api_version
reverse_set_default_stripe_api_version = migration_module.reverse_set_default_stripe_api_version

LEGACY_STRIPE_API_VERSION = "2024-09-30.acacia"


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
class TestSetDefaultStripeApiVersion:
    @pytest.mark.parametrize(
        "input_job_inputs, expected_job_inputs",
        [
            (
                {"auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_test123"}},
                {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_test123"},
                    "stripe_api_version": LEGACY_STRIPE_API_VERSION,
                },
            ),
            (
                {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_test123"},
                    "stripe_api_version": "2026-02-25.clover",
                },
                {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_test123"},
                    "stripe_api_version": "2026-02-25.clover",
                },
            ),
        ],
        ids=["no_version_gets_legacy", "existing_version_preserved"],
    )
    def test_forward_migration(self, input_job_inputs, expected_job_inputs, stripe_source_factory):
        source = stripe_source_factory(input_job_inputs)

        set_default_stripe_api_version(apps, None)

        source.refresh_from_db()
        assert source.job_inputs == expected_job_inputs

    @pytest.mark.parametrize(
        "input_job_inputs, expected_job_inputs",
        [
            (
                {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_test123"},
                    "stripe_api_version": LEGACY_STRIPE_API_VERSION,
                },
                {"auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_test123"}},
            ),
            (
                {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_test123"},
                    "stripe_api_version": "2026-02-25.clover",
                },
                {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "rk_live_test123"},
                    "stripe_api_version": "2026-02-25.clover",
                },
            ),
        ],
        ids=["legacy_version_removed", "non_legacy_version_preserved"],
    )
    def test_reverse_migration(self, input_job_inputs, expected_job_inputs, stripe_source_factory):
        source = stripe_source_factory(input_job_inputs)

        reverse_set_default_stripe_api_version(apps, None)

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

        set_default_stripe_api_version(apps, None)

        github_source.refresh_from_db()
        assert github_source.job_inputs == {"personal_access_token": "ghp_test123"}
