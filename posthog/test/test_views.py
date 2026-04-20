from unittest.mock import patch

from django.test import Client

from posthog.models.proxy_record import ProxyRecord
from posthog.test.base import BaseTest


class TestRobotsTxt(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()

    @patch("posthog.views.is_cloud", return_value=False)
    def test_self_hosted_disallows_all(self, _mock_is_cloud):
        response = self.client.get("/robots.txt")
        assert response.status_code == 200
        assert response.content == b"User-agent: *\nDisallow: /"

    @patch("posthog.views.is_cloud", return_value=True)
    def test_cloud_allows_most_paths(self, _mock_is_cloud):
        response = self.client.get("/robots.txt")
        assert response.status_code == 200
        assert b"User-agent: *" in response.content
        assert b"Disallow: /e/" in response.content
        assert b"Disallow: /shared_dashboard/" in response.content

    @patch("posthog.views.is_cloud", return_value=True)
    def test_managed_proxy_domain_disallows_all(self, _mock_is_cloud):
        ProxyRecord.objects.create(
            organization=self.organization,
            domain="proxy.example.com",
            target_cname="target.posthog.com",
            status=ProxyRecord.Status.VALID,
        )

        response = self.client.get("/robots.txt", HTTP_HOST="proxy.example.com")

        assert response.status_code == 200
        assert response.content == b"User-agent: *\nDisallow: /"

    @patch("posthog.views.is_cloud", return_value=True)
    def test_non_proxy_domain_returns_cloud_robots(self, _mock_is_cloud):
        response = self.client.get("/robots.txt", HTTP_HOST="app.posthog.com")

        assert response.status_code == 200
        assert b"Disallow: /e/" in response.content

    @patch("posthog.views.is_cloud", return_value=True)
    def test_non_valid_proxy_record_returns_cloud_robots(self, _mock_is_cloud):
        ProxyRecord.objects.create(
            organization=self.organization,
            domain="pending.example.com",
            target_cname="target.posthog.com",
            status=ProxyRecord.Status.WAITING,
        )

        response = self.client.get("/robots.txt", HTTP_HOST="pending.example.com")

        assert response.status_code == 200
        assert b"Disallow: /e/" in response.content
