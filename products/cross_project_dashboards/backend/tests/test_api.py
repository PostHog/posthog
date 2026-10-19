import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import Organization
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.cross_project_dashboards.backend.models import CrossProjectDashboard


@patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
class TestCrossProjectDashboardAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/organizations/{self.organization.id}/cross_project_dashboards/{suffix}"

    def _dashboard(self) -> CrossProjectDashboard:
        return CrossProjectDashboard.objects.create(
            organization=self.organization, name="Company overview", created_by=self.user
        )

    def test_creates_a_dashboard(self, _flag):
        response = self.client.post(self._url(), {"name": "Company overview"})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["name"] == "Company overview"

    def test_rejects_a_project_bound_filter(self, _flag):
        response = self.client.post(
            self._url(),
            {"name": "X", "filters": {"properties": [{"type": "cohort", "key": "id", "value": 42}]}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "cohort" in str(response.json())

    def test_rejects_filters_over_the_size_ceiling(self, _flag):
        response = self.client.post(self._url(), {"name": "Big", "filters": {"padding": "x" * 20_000}}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_allows_a_date_filter(self, _flag):
        response = self.client.post(
            self._url(), {"name": "X", "filters": {"date_from": "-7d", "interval": "week"}}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

    def test_does_not_return_another_organizations_dashboard(self, _flag):
        other_organization = Organization.objects.create(name="Other")
        other = CrossProjectDashboard.objects.create(organization=other_organization, name="Theirs")
        response = self.client.get(self._url(f"{other.id}/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_pages_through_dashboards_created_in_the_same_instant(self, _flag):
        with time_machine.travel("2026-01-01T00:00:00Z", tick=False):
            created = {str(self._dashboard().id) for _ in range(3)}

        first = self.client.get(self._url("?limit=2")).json()
        second = self.client.get(self._url("?limit=2&offset=2")).json()

        paged = [dashboard["id"] for dashboard in first["results"] + second["results"]]
        assert first["count"] == 3
        assert sorted(paged) == sorted(created)

    def test_rejects_a_project_scoped_key_even_with_a_capture_token(self, _flag):
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Project only",
            user=self.user,
            secure_value=hash_key_value(key),
            scopes=["cross_project_dashboard:read"],
            scoped_teams=[self.team.id],
        )
        self.client.logout()

        response = self.client.get(self._url(f"?token={self.team.api_token}"), HTTP_AUTHORIZATION=f"Bearer {key}")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_delete_is_a_soft_delete(self, _flag):
        dashboard = self._dashboard()
        response = self.client.delete(self._url(f"{dashboard.id}/"))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        dashboard.refresh_from_db()
        assert dashboard.deleted is True

    def test_denies_everything_when_the_flag_is_off(self, flag):
        flag.return_value = False
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_403_FORBIDDEN
