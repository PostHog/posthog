from datetime import UTC, datetime

import pytest
from freezegun import freeze_time

from posthog.dags.exported_asset_expiry_backfill import exported_asset_expiry_backfill_job
from posthog.models.exported_asset import SIX_MONTHS, ExportedAsset
from posthog.models.team import Team


def create_asset_without_expiry(team: Team) -> ExportedAsset:
    """Use bulk_create to create an asset without expires_after (bypasses save())."""
    assets = ExportedAsset.objects.bulk_create(
        [
            ExportedAsset(
                team=team,
                export_format=ExportedAsset.ExportFormat.PNG,
            )
        ]
    )
    return assets[0]


@pytest.fixture
def team(db):
    from posthog.models.organization import Organization

    org = Organization.objects.create(name="Test Org")
    return Team.objects.create(name="Test Team", organization=org)


@pytest.mark.django_db
@freeze_time("2024-06-15T10:30:00Z")
def test_backfill_updates_null_expires_after(team):
    asset = create_asset_without_expiry(team)

    result = exported_asset_expiry_backfill_job.execute_in_process()

    assert result.success
    asset.refresh_from_db()
    expected_expiry = (datetime(2024, 6, 15, tzinfo=UTC) + SIX_MONTHS).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    assert asset.expires_after == expected_expiry


@pytest.mark.django_db
@freeze_time("2024-06-15T10:30:00Z")
def test_does_not_update_assets_with_existing_expiry(team):
    custom_expiry = datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)
    asset = ExportedAsset.objects.create(
        team=team,
        export_format=ExportedAsset.ExportFormat.PNG,
        expires_after=custom_expiry,
    )

    result = exported_asset_expiry_backfill_job.execute_in_process()

    assert result.success
    asset.refresh_from_db()
    assert asset.expires_after == custom_expiry


@pytest.mark.django_db
def test_backfill_uses_created_at_not_now(team):
    created_at = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    with freeze_time(created_at):
        asset = create_asset_without_expiry(team)

    with freeze_time("2024-06-15T10:00:00Z"):
        result = exported_asset_expiry_backfill_job.execute_in_process()

    assert result.success
    asset.refresh_from_db()
    expiry_delta = ExportedAsset.get_expiry_delta(asset.export_format)
    expected_expiry = (created_at + expiry_delta).replace(hour=0, minute=0, second=0, microsecond=0)
    assert asset.expires_after == expected_expiry


@pytest.mark.django_db
@freeze_time("2024-06-15T10:30:00Z")
def test_reports_correct_count(team):
    for _ in range(3):
        create_asset_without_expiry(team)
    # Create an asset with existing expiry - should not be counted
    ExportedAsset.objects.create(
        team=team,
        export_format=ExportedAsset.ExportFormat.PNG,
        expires_after=datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
    )

    result = exported_asset_expiry_backfill_job.execute_in_process()

    assert result.success
    count_output = result.output_for_node("get_null_expiry_count")
    assert count_output == 3


@pytest.mark.django_db
@freeze_time("2024-06-15T10:30:00Z")
def test_bulk_update_across_multiple_batches(team):
    assets = [create_asset_without_expiry(team) for _ in range(5)]

    result = exported_asset_expiry_backfill_job.execute_in_process(
        run_config={
            "ops": {
                "backfill_expiry_batch": {"config": {"batch_size": 2}},
            }
        }
    )

    assert result.success
    expected_expiry = (datetime(2024, 6, 15, tzinfo=UTC) + SIX_MONTHS).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    for asset in assets:
        asset.refresh_from_db()
        assert asset.expires_after == expected_expiry
