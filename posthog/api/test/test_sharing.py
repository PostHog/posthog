import secrets
from freezegun import freeze_time
from rest_framework import status

from posthog.models.dashboard import Dashboard
from posthog.models.filters.filter import Filter
from posthog.models.insight import Insight
from posthog.models.sharing_configuration import SharingConfiguration
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
        assert data["enabled"] == True

    def test_should_update_to_match_existing_dashboard_sharing_token(self):
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing")
        initial_token = response.json()["access_token"]
        assert initial_token
        assert response.json()["enabled"] == False

        self.dashboard.share_token = "my_test_token"
        self.dashboard.is_shared = True
        self.dashboard.save()

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing")
        data = response.json()
        assert data["access_token"] == "my_test_token"
        assert data["enabled"] == True

        self.dashboard.share_token = None
        self.dashboard.is_shared = False
        self.dashboard.save()

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard.id}/sharing")
        data = response.json()
        assert data["access_token"] == "my_test_token"
        assert data["enabled"] == True
