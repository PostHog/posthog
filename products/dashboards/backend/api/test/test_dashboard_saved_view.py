from posthog.test.base import APIBaseTest

from rest_framework import status


class TestLegacyDashboardSavedViews(APIBaseTest):
    def test_list_returns_an_empty_page_for_stale_frontend_bundles(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_saved_views/?limit=100&scope=private")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"next": None, "previous": None, "results": []}

    def test_writes_are_not_accepted(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_saved_views/", {"name": "View"}, format="json"
        )

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
