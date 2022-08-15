from unittest.mock import patch

from freezegun import freeze_time
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

    insight_filter_dict = {
        "events": [{"id": "$pageview"}],
        "properties": [{"key": "$browser", "value": "Mac OS X"}],
    }

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
        assert SharingConfiguration.objects.count() == 1
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data == {
            "access_token": data["access_token"],
            "created_at": "2022-01-01T00:00:00Z",
            "enabled": False,
        }

        assert len(data["access_token"]) > 0

        response2 = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing")
        assert data["access_token"] == response2.json()["access_token"]
        assert SharingConfiguration.objects.count() == 1

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
            team=self.team, name="example dashboard", created_by=self.user, share_token="my_test_token", is_shared=True,
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/sharing", {"enabled": True}
        )
        response = self.client.get(f"/shared_dashboard/my_test_token")
        assert response.status_code == 200
        response = self.client.patch(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}", {"deleted": True})
        response = self.client.get(f"/shared_dashboard/my_test_token")
        assert response.status_code == 404

    @patch("posthog.models.exported_asset.object_storage.read_bytes")
    @patch("posthog.api.sharing.asset_for_token")
    def test_can_get_shared_dashboard_asset_with_no_content_but_content_location(
        self, patched_asset_for_token, patched_object_storage
    ) -> None:
        asset = ExportedAsset.objects.create(
            team_id=self.team.id,
            export_format=ExportedAsset.ExportFormat.PNG,
            content=None,
            content_location="some object url",
        )
        patched_asset_for_token.return_value = asset

        patched_object_storage.return_value = b"the image bytes"

        # pytest parameterize doesn't work in unittest.TestCase classes :'(
        for url in [
            "/exporter/something.png?token=my_test_token",
            "/shared_dashboard/something.png?token=my_test_token",
        ]:
            response = self.client.get(url)

            assert response.status_code == 200
            assert response.headers.get("Content-Type") == "image/png"
            assert response.content == b"the image bytes"
