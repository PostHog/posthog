from django.test.client import Client as TestClient

from posthog.api.test.test_organization import create_organization as create_organization_base
from posthog.models import Organization, Team, User
from posthog.models.integration import Integration

from products.batch_exports.backend.models.batch_export import (
    BatchExport,
    BatchExportBackfill,
    BatchExportDestination,
    BatchExportRun,
)
from products.batch_exports.backend.tests.api.operations import create_batch_export_ok


def create_organization(name: str) -> Organization:
    organization = create_organization_base(name)
    return organization


def create_team(organization: Organization, name: str = "Test team", timezone: str = "UTC") -> Team:
    """
    This is a helper that just creates a team. It currently uses the orm, but we
    could use either the api, or django admin to create, to get better parity
    with real world scenarios.
    """
    return Team.objects.create(
        organization=organization,
        name=name,
        ingested_event=True,
        completed_snippet_onboarding=True,
        is_demo=True,
        timezone=timezone,
        base_currency="USD",
    )


def create_user(email: str, password: str, organization: Organization):
    """
    Helper that just creates a user. It currently uses the orm, but we
    could use either the api, or django admin to create, to get better parity
    with real world scenarios.
    """
    return User.objects.create_and_join(organization, email, password)


def create_destination() -> BatchExportDestination:
    """Create a test batch export destination."""
    return BatchExportDestination.objects.create(
        type="S3",
        config={
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
        },
    )


def create_batch_export(team, destination) -> BatchExport:
    """Create a test batch export."""
    return BatchExport.objects.create(
        team=team,
        name="my-production-s3-bucket-destination",
        destination=destination,
        interval="hour",
    )


def create_integration_backed_snowflake_export(client: TestClient, team: Team, user: User) -> tuple[Integration, dict]:
    """Create a Snowflake integration and an integration-backed batch export using it.

    Returns the integration and the created batch export (as returned by the API).
    """
    integration = Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.SNOWFLAKE,
        integration_id="prod-snowflake",
        config={"name": "prod-snowflake", "account": "my-account", "user": "svc", "authentication_type": "password"},
        sensitive_config={"password": "secret"},
        created_by=user,
    )
    export_data = {
        "name": "my-export",
        "interval": "hour",
        "destination": {
            "type": "Snowflake",
            # No account/user/credentials inline — they come from the integration.
            "config": {"database": "my-db", "warehouse": "COMPUTE_WH", "schema": "public"},
            "integration": integration.pk,
        },
    }
    client.force_login(user)
    batch_export = create_batch_export_ok(client, team.pk, export_data)
    return integration, batch_export


def create_backfill(team, batch_export, start_at, end_at, status, finished_at) -> BatchExportBackfill:
    """Create test backfill."""
    return BatchExportBackfill.objects.create(
        batch_export=batch_export,
        team=team,
        start_at=start_at,
        end_at=end_at,
        status=status,
        finished_at=finished_at,
    )


def create_run(batch_export, status, data_interval_start, data_interval_end, backfill=None) -> BatchExportRun:
    """Create a test batch export run."""
    return BatchExportRun.objects.create(
        batch_export=batch_export,
        status=status,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        backfill=backfill,
    )
