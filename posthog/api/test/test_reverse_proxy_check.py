from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from rest_framework import status

from posthog.models.organization import Organization


@patch("posthog.models.team.reverse_proxy_check.execute_hogql_query")
class TestReverseProxyCheckAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_returns_the_check_for_the_users_team(self, mock_query: MagicMock) -> None:
        mock_query.return_value = MagicMock(results=[["https://proxy.example.com"]])

        response = self.client.get(f"/api/projects/{self.team.pk}/reverse_proxy/check/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"has_reverse_proxy": True}
        assert mock_query.call_args.kwargs["team"].pk == self.team.pk

    def test_refuses_a_team_the_user_cannot_access(self, mock_query: MagicMock) -> None:
        other_team = Organization.objects.bootstrap(None)[2]

        response = self.client.get(f"/api/projects/{other_team.pk}/reverse_proxy/check/")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_query.assert_not_called()
