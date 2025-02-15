from posthog.api.test.test_organization import (
    create_organization as create_organization_base,
)
from posthog.constants import AvailableFeature
from posthog.models import (
    BatchExport,
    BatchExportBackfill,
    BatchExportDestination,
    BatchExportRun,
    Organization,
)


def create_organization(name: str, has_data_pipelines_feature: bool = True) -> Organization:
    organization = create_organization_base(name)
    if has_data_pipelines_feature:
        organization.available_product_features = [
            {"key": AvailableFeature.DATA_PIPELINES, "name": AvailableFeature.DATA_PIPELINES}
        ]
        organization.save()
    return organization


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
