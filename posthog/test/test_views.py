from unittest.mock import patch

from django.test import Client

from parameterized import parameterized

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

    @parameterized.expand(
        [
            ("valid_proxy_domain", "proxy.example.com", ProxyRecord.Status.VALID, b"User-agent: *\nDisallow: /"),
            ("non_proxy_domain", "app.posthog.com", None, b"Disallow: /e/"),
            ("waiting_proxy_domain", "pending.example.com", ProxyRecord.Status.WAITING, b"Disallow: /e/"),
        ]
    )
    @patch("posthog.views.is_cloud", return_value=True)
    def test_cloud_proxy_handling(self, _name, host, proxy_status, expected_content, _mock_is_cloud):
        if proxy_status is not None:
            ProxyRecord.objects.create(
                organization=self.organization,
                domain=host,
                target_cname="target.posthog.com",
                status=proxy_status,
            )

        response = self.client.get("/robots.txt", HTTP_HOST=host)

        assert response.status_code == 200
        assert expected_content in response.content
