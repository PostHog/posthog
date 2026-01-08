from datetime import UTC, datetime
from io import StringIO

from freezegun import freeze_time
from posthog.test.base import BaseTest

from django.core.management import call_command

from posthog.models.exported_asset import SIX_MONTHS, ExportedAsset


class TestBackfillExportedAssetExpiry(BaseTest):
    def _create_asset_without_expiry(self) -> ExportedAsset:
        """Use bulk_create to create an asset without expires_after (bypasses save())."""
        assets = ExportedAsset.objects.bulk_create(
            [
                ExportedAsset(
                    team=self.team,
                    export_format=ExportedAsset.ExportFormat.PNG,
                )
            ]
        )
        return assets[0]

    @freeze_time("2024-06-15T10:30:00Z")
    def test_dry_run_does_not_update(self) -> None:
        asset = self._create_asset_without_expiry()

        out = StringIO()
        call_command("backfill_exported_asset_expiry", stdout=out)

        asset.refresh_from_db()
        assert asset.expires_after is None
        assert "Dry run" in out.getvalue()

    @freeze_time("2024-06-15T10:30:00Z")
    def test_live_run_updates_null_expires_after(self) -> None:
        asset = self._create_asset_without_expiry()

        out = StringIO()
        call_command("backfill_exported_asset_expiry", "--live-run", stdout=out)

        asset.refresh_from_db()
        expected_expiry = (datetime(2024, 6, 15, tzinfo=UTC) + SIX_MONTHS).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        assert asset.expires_after == expected_expiry
        assert "Done!" in out.getvalue()

    @freeze_time("2024-06-15T10:30:00Z")
    def test_does_not_update_assets_with_existing_expiry(self) -> None:
        custom_expiry = datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            expires_after=custom_expiry,
        )

        out = StringIO()
        call_command("backfill_exported_asset_expiry", "--live-run", stdout=out)

        asset.refresh_from_db()
        assert asset.expires_after == custom_expiry
        assert "Nothing to backfill" in out.getvalue()

    @freeze_time("2024-06-15T10:30:00Z")
    def test_reports_correct_count(self) -> None:
        for _ in range(3):
            self._create_asset_without_expiry()

        out = StringIO()
        call_command("backfill_exported_asset_expiry", stdout=out)

        assert "Found 3 ExportedAssets" in out.getvalue()

    def test_backfill_uses_created_at_not_now(self) -> None:
        created_at = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        with freeze_time(created_at):
            asset = self._create_asset_without_expiry()

        with freeze_time("2024-06-15T10:00:00Z"):
            call_command("backfill_exported_asset_expiry", "--live-run", stdout=StringIO())

        asset.refresh_from_db()
        expiry_delta = ExportedAsset.get_expiry_delta(asset.export_format)
        expected_expiry = (created_at + expiry_delta).replace(hour=0, minute=0, second=0, microsecond=0)
        assert asset.expires_after == expected_expiry

    @freeze_time("2024-06-15T10:30:00Z")
    def test_bulk_update_across_multiple_batches(self) -> None:
        """Verify that bulk_update works correctly with multiple batches including a partial final batch."""
        assets = [self._create_asset_without_expiry() for _ in range(5)]

        out = StringIO()
        call_command("backfill_exported_asset_expiry", "--live-run", "--batch-size=2", stdout=out)

        expected_expiry = (datetime(2024, 6, 15, tzinfo=UTC) + SIX_MONTHS).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        for asset in assets:
            asset.refresh_from_db()
            assert asset.expires_after == expected_expiry

        assert "Updated 5 ExportedAssets" in out.getvalue()
