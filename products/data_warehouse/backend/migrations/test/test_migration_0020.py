import uuid
import importlib

import pytest

from django.apps import apps

from products.data_warehouse.backend.models import ExternalDataSource

migration_module = importlib.import_module(
    "products.data_warehouse.backend.migrations.0020_migrate_github_job_inputs_to_auth_type"
)
migrate_github_job_inputs = migration_module.migrate_github_job_inputs
reverse_migrate_github_job_inputs = migration_module.reverse_migrate_github_job_inputs


@pytest.fixture
def github_source_factory(team):
    def _create(job_inputs):
        return ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Github",
            job_inputs=job_inputs,
        )

    return _create


@pytest.mark.django_db
class TestMigrateGithubJobInputs:
    @pytest.mark.parametrize(
        "input_job_inputs, expected_job_inputs",
        [
            (
                {"personal_access_token": "ghp_test123", "repository": "owner/repo"},
                {
                    "auth_method": {"selection": "pat", "personal_access_token": "ghp_test123"},
                    "repository": "owner/repo",
                },
            ),
            (
                {"github_integration_id": 42, "repository": "org/project"},
                {
                    "auth_method": {"selection": "oauth", "github_integration_id": "42"},
                    "repository": "org/project",
                },
            ),
            (
                {
                    "auth_method": {"selection": "pat", "personal_access_token": "ghp_existing"},
                    "repository": "owner/repo",
                },
                {
                    "auth_method": {"selection": "pat", "personal_access_token": "ghp_existing"},
                    "repository": "owner/repo",
                },
            ),
        ],
        ids=["pat_to_nested", "oauth_to_nested", "already_migrated_skipped"],
    )
    def test_forward_migration(self, input_job_inputs, expected_job_inputs, github_source_factory):
        source = github_source_factory(input_job_inputs)

        migrate_github_job_inputs(apps, None)

        source.refresh_from_db()
        assert source.job_inputs == expected_job_inputs

    @pytest.mark.parametrize(
        "input_job_inputs, expected_job_inputs",
        [
            (
                {
                    "auth_method": {"selection": "pat", "personal_access_token": "ghp_test123"},
                    "repository": "owner/repo",
                },
                {"personal_access_token": "ghp_test123", "repository": "owner/repo"},
            ),
            (
                {
                    "auth_method": {"selection": "oauth", "github_integration_id": "42"},
                    "repository": "org/project",
                },
                {"github_integration_id": "42", "repository": "org/project"},
            ),
        ],
        ids=["nested_pat_to_flat", "nested_oauth_to_flat"],
    )
    def test_reverse_migration(self, input_job_inputs, expected_job_inputs, github_source_factory):
        source = github_source_factory(input_job_inputs)

        reverse_migrate_github_job_inputs(apps, None)

        source.refresh_from_db()
        assert source.job_inputs == expected_job_inputs

    def test_non_github_sources_unaffected(self, team):
        stripe_source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )

        migrate_github_job_inputs(apps, None)

        stripe_source.refresh_from_db()
        assert stripe_source.job_inputs == {"stripe_secret_key": "sk_test_123"}
