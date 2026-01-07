from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.exported_asset import SEVEN_DAYS, SIX_MONTHS, TWELVE_MONTHS, ExportedAsset


class TestExportedAssetModel(APIBaseTest):
    def test_exported_asset_inside_ttl_is_visible_to_both_managers(self) -> None:
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            expires_after=datetime.now() + timedelta(seconds=100),
        )

        assert list(ExportedAsset.objects.filter(id=asset.id)) == [asset]
        assert list(ExportedAsset.objects_including_ttl_deleted.filter(id=asset.id)) == [asset]

    def test_exported_asset_without_ttl_is_visible_to_both_managers(self) -> None:
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
        )

        assert list(ExportedAsset.objects.filter(id=asset.id)) == [asset]
        assert list(ExportedAsset.objects_including_ttl_deleted.filter(id=asset.id)) == [asset]

    def test_exported_asset_outside_ttl_is_not_visible_to_both_managers(self) -> None:
        with freeze_time("2021-01-01T12:00:00Z") as frozen_time:
            asset = ExportedAsset.objects.create(
                team=self.team,
                created_by=self.user,
                expires_after=datetime.now() + timedelta(seconds=100),
            )

            frozen_time.tick(delta=timedelta(seconds=101))

            assert list(ExportedAsset.objects.filter(id=asset.id)) == []
            assert list(ExportedAsset.objects_including_ttl_deleted.filter(id=asset.id)) == [asset]

    def test_delete_expired_assets(self) -> None:
        assert ExportedAsset.objects.count() == 0

        ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            # expires in the past, should be deleted
            expires_after=datetime.now() - timedelta(days=1),
        )
        asset_that_is_not_expired = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            # expires in the future should not be deleted
            expires_after=datetime.now() + timedelta(days=1),
        )

        asset_that_has_no_expiry = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
        )

        assert ExportedAsset.objects.count() == 2
        assert ExportedAsset.objects_including_ttl_deleted.count() == 3

        ExportedAsset.delete_expired_assets()

        assert list(ExportedAsset.objects.all()) == [
            asset_that_is_not_expired,
            asset_that_has_no_expiry,
        ]
        assert list(ExportedAsset.objects_including_ttl_deleted.all()) == [
            asset_that_is_not_expired,
            asset_that_has_no_expiry,
        ]


class TestExportedAssetExpiresAfter(APIBaseTest):
    @parameterized.expand(
        [
            (ExportedAsset.ExportFormat.PNG, SIX_MONTHS),
            (ExportedAsset.ExportFormat.PDF, SIX_MONTHS),
            (ExportedAsset.ExportFormat.CSV, SEVEN_DAYS),
            (ExportedAsset.ExportFormat.XLSX, SEVEN_DAYS),
            (ExportedAsset.ExportFormat.MP4, TWELVE_MONTHS),
            (ExportedAsset.ExportFormat.WEBM, TWELVE_MONTHS),
            (ExportedAsset.ExportFormat.GIF, TWELVE_MONTHS),
            (ExportedAsset.ExportFormat.JSON, SIX_MONTHS),
        ]
    )
    )
    @freeze_time("2024-06-15T10:30:00Z")
    def test_auto_sets_expires_after_based_on_format(self, export_format: str, expected_delta: timedelta) -> None:
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=export_format,
        )

        expected_expiry = (datetime(2024, 6, 15, tzinfo=UTC) + expected_delta).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        assert asset.expires_after == expected_expiry

    @freeze_time("2024-06-15T10:30:00Z")
    def test_respects_explicit_expires_after(self) -> None:
        custom_expiry = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            expires_after=custom_expiry,
        )

        assert asset.expires_after == custom_expiry

    @freeze_time("2024-06-15T10:30:00Z")
    def test_partial_save_does_not_overwrite_existing_expires_after(self) -> None:
        custom_expiry = datetime(2025, 12, 22, 0, 0, 0, tzinfo=UTC)
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            expires_after=custom_expiry,
        )

        asset.exception = "some error"
        asset.save(update_fields=["exception"])

        asset.refresh_from_db()
        assert asset.expires_after == custom_expiry

    @freeze_time("2024-06-15T10:30:00Z")
    def test_explicitly_updating_expires_after_field(self) -> None:
        custom_expiry = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            expires_after=custom_expiry,
        )
        assert asset.expires_after == custom_expiry

        new_expiry = datetime(2025, 12, 22, 0, 0, 0, tzinfo=UTC)
        asset.expires_after = new_expiry
        asset.save(update_fields=["expires_after"])
        asset.refresh_from_db()
        assert asset.expires_after == new_expiry
