from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from posthog.models.exported_asset import ExportedAsset


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
