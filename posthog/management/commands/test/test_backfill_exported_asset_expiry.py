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
        custom_expiry = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
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
