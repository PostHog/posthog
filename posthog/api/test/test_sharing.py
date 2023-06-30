from datetime import timedelta
from unittest.mock import patch, Mock, MagicMock

from django.utils.timezone import now
from freezegun import freeze_time
from parameterized import parameterized
from rest_framework import status

from posthog.models import ExportedAsset
from posthog.models.dashboard import Dashboard
from posthog.models.filters.filter import Filter
from posthog.models.insight import Insight
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User
from posthog.test.base import APIBaseTest


class TestSharing(APIBaseTest):
    dashboard: Dashboard = None  # type: ignore
    insight: Insight = None  # type: ignore

    insight_filter_dict = {"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}]}

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.dashboard = Dashboard.objects.create(team=cls.team, name="example dashboard", created_by=cls.user)
        cls.insight = Insight.objects.create(
            filters=Filter(data=cls.insight_filter_dict).to_dict(), team=cls.team, created_by=cls.user
        )

    @freeze_time("2022-01-01")
    def test_gets_sharing_config(self):
        assert SharingConfiguration.objects.count() == 0

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing")
        assert SharingConfiguration.objects.count() == 0
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data == {"access_token": data["access_token"], "created_at": None, "enabled": False}

    @freeze_time("2022-01-01")
    def test_does_not_change_token_when_toggling_enabled_state(self):
        assert SharingConfiguration.objects.count() == 0
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing", {"enabled": True}
        )
        initial_data = response.json()
        assert SharingConfiguration.objects.count() == 1
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing")
        assert response.json() == {
            "access_token": initial_data["access_token"],
            "created_at": "2022-01-01T00:00:00Z",
            "enabled": True,
        }

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing", {"enabled": False}
        )
        assert response.json() == {
            "access_token": initial_data["access_token"],
            "created_at": "2022-01-01T00:00:00Z",
            "enabled": False,
        }

    def test_can_edit_enabled_state(self):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing", {"enabled": True}
        )
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert data["enabled"]

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}")

        assert response.json()["is_shared"]

    def test_should_update_to_match_existing_dashboard_sharing_token(self):
        dashboard = Dashboard.objects.create(team=self.team, name="example dashboard", created_by=self.user)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing")
        initial_token = response.json()["access_token"]
        assert initial_token
        assert not response.json()["enabled"]

        dashboard.share_token = "my_test_token"
        dashboard.is_shared = True
        dashboard.save()

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing")
        data = response.json()
        assert data["access_token"] == "my_test_token"
        assert data["enabled"]

        dashboard.share_token = None
        dashboard.is_shared = False
        dashboard.save()

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing")
        data = response.json()
        assert data["access_token"] == "my_test_token"
        assert data["enabled"]

    def test_should_not_be_affected_by_collaboration_rules(self):
        other_user = User.objects.create_and_join(self.organization, "a@x.com", None)
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="example dashboard",
            created_by=other_user,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing", {"enabled": True}
        )

        assert response.status_code == 200

    def test_should_not_get_deleted_item(self):
        dashboard = Dashboard.objects.create(
            team=self.team, name="example dashboard", created_by=self.user, share_token="my_test_token", is_shared=True
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing", {"enabled": True}
        )
        response = self.client.get(f"/shared_dashboard/my_test_token")
        assert response.status_code == 200
        response = self.client.patch(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}", {"deleted": True})
        response = self.client.get(f"/shared_dashboard/my_test_token")
        assert response.status_code == 404

    @parameterized.expand(
        [
            "/exporter/something.png?token=my_test_token",
            "/shared_dashboard/something.png?token=my_test_token",
        ]
    )
    @patch("posthog.models.exported_asset.object_storage.read_bytes")
    @patch("posthog.api.sharing.asset_for_token")
    def test_can_get_shared_dashboard_asset_with_no_content_but_content_location(
        self, url: str, patched_asset_for_token, patched_object_storage
    ) -> None:
        asset = ExportedAsset.objects.create(
            team_id=self.team.id,
            export_format=ExportedAsset.ExportFormat.PNG,
            content=None,
            content_location="some object url",
        )
        patched_asset_for_token.return_value = asset

        patched_object_storage.return_value = b"the image bytes"

        response = self.client.get(url)

        assert response.status_code == 200
        assert response.headers.get("Content-Type") == "image/png"
        assert response.content == b"the image bytes"

    @parameterized.expand(["insights", "dashboards"])
    @patch("posthog.models.exported_asset.object_storage.read_bytes")
    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_shared_thing_can_generate_open_graph_image(
        self, type: str, patched_exporter_task: Mock, patched_object_storage: Mock
    ) -> None:
        patched_object_storage.return_value = b"the image bytes"

        target = self.insight if type == "insights" else self.dashboard

        share_response = self.client.patch(
            f"/api/projects/{self.team.id}/{type}/{target.pk}/sharing", {"enabled": True}
        )
        access_token = share_response.json()["access_token"]

        def add_content_location_on_task_run(*args, **kwargs):
            asset = ExportedAsset.objects.get(team_id=self.team.id)
            asset.content_location = "some object url"
            asset.save()

            return MagicMock()

        patched_exporter_task.side_effect = add_content_location_on_task_run

        assert ExportedAsset.objects.count() == 0

        item_opengraph_image = self.client.get("/shared/" + access_token + ".png")

        assert ExportedAsset.objects.count() == 1
        assert item_opengraph_image.status_code == 200
        assert item_opengraph_image.headers["Content-Type"] == "image/png"
        assert item_opengraph_image.content == b"the image bytes"

    @parameterized.expand(["insights", "dashboards"])
    @patch("posthog.models.exported_asset.object_storage.read_bytes")
    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_shared_thing_can_reuse_existing_generated_open_graph_image(
        self, type: str, patched_exporter_task: Mock, patched_object_storage: Mock
    ) -> None:
        patched_object_storage.return_value = b"the image bytes"

        target = self.insight if type == "insights" else self.dashboard

        share_response = self.client.patch(
            f"/api/projects/{self.team.id}/{type}/{target.pk}/sharing", {"enabled": True}
        )
        access_token = share_response.json()["access_token"]

        ExportedAsset.objects.create(
            team_id=self.team.id,
            export_format=ExportedAsset.ExportFormat.PNG,
            content=None,
            content_location="existing object url",
            insight=self.insight if type == "insights" else None,
            dashboard=self.dashboard if type == "dashboards" else None,
        )
        assert ExportedAsset.objects.count() == 1

        item_opengraph_image = self.client.get("/shared/" + access_token + ".png")

        patched_exporter_task.assert_not_called()

        assert ExportedAsset.objects.count() == 1
        assert item_opengraph_image.status_code == 200
        assert item_opengraph_image.headers["Content-Type"] == "image/png"
        assert item_opengraph_image.content == b"the image bytes"

    @parameterized.expand(["insights", "dashboards"])
    @patch("posthog.models.exported_asset.object_storage.read_bytes")
    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_shared_insight_can_regenerate_stale_existing_generated_open_graph_image(
        self, type: str, patched_exporter_task: Mock, patched_object_storage: Mock
    ) -> None:
        patched_object_storage.return_value = b"the image bytes"

        target = self.insight if type == "insights" else self.dashboard

        share_response = self.client.patch(
            f"/api/projects/{self.team.id}/{type}/{target.pk}/sharing", {"enabled": True}
        )
        access_token = share_response.json()["access_token"]

        # the existing asset is stale because it is more than 3 hours old
        time_in_the_past = now() - timedelta(hours=4)
        asset = ExportedAsset.objects.create(
            team_id=self.team.id,
            export_format=ExportedAsset.ExportFormat.PNG,
            content=None,
            content_location="existing object url",
            insight=self.insight if type == "insights" else None,
            dashboard=self.dashboard if type == "dashboards" else None,
        )
        asset.created_at = time_in_the_past
        asset.save()

        def add_content_location_on_task_run(*args, **kwargs):
            asset = ExportedAsset.objects.get(team_id=self.team.id)
            asset.content_location = "some object url"
            asset.save()

            return MagicMock()

        patched_exporter_task.side_effect = add_content_location_on_task_run

        assert ExportedAsset.objects.count() == 1

        item_opengraph_image = self.client.get("/shared/" + access_token + ".png")

        assert ExportedAsset.objects.count() == 1
        final_asset = ExportedAsset.objects.first()
        assert final_asset is not None
        assert final_asset.id != asset.id

        assert item_opengraph_image.status_code == 200
        assert item_opengraph_image.headers["Content-Type"] == "image/png"
        assert item_opengraph_image.content == b"the image bytes"
