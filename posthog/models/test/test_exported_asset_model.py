import datetime

from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models.exported_asset import ExportedAsset
from posthog.test.base import APIBaseTest


class TestExportedAssetModel(APIBaseTest):
    def test_exported_asset_inside_ttl_is_visible_to_both_managers(self) -> None:
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            expires_after=now() + datetime.timedelta(seconds=100),
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
                expires_after=now() + datetime.timedelta(seconds=100),
            )

            frozen_time.tick(delta=datetime.timedelta(seconds=101))

            assert list(ExportedAsset.objects.filter(id=asset.id)) == []
            assert list(ExportedAsset.objects_including_ttl_deleted.filter(id=asset.id)) == [asset]
