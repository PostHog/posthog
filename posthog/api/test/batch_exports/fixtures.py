from posthog.api.test.test_organization import create_organization as create_organization_base
from posthog.models import (
    BatchExport,
    BatchExportBackfill,
    BatchExportDestination,
    BatchExportRun,
    Organization,
    Team,
    User,
)


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
