import ipaddress

import pytest
from unittest.mock import MagicMock, patch

import requests
from requests.adapters import HTTPAdapter

from posthog.security import pinned_requests as pr


class TestPinnedRequest:
    def test_blocked_url_raises_before_any_connection(self):
        with (
            patch.object(pr, "validate_url_and_pin_ips", return_value=(False, "Loopback host", set())),
            patch.object(pr.requests, "Session") as session_cls,
        ):
            with pytest.raises(pr.SSRFBlockedError, match="Loopback host"):
                pr.pinned_request("GET", "http://127.0.0.1/admin", timeout=5)
        session_cls.assert_not_called()


class TestPinnedIPAdapter:
    @pytest.mark.parametrize(
        "ip,expected_netloc",
        [
            ("93.184.216.34", "93.184.216.34:8443"),
            ("2001:db8::1", "[2001:db8::1]:8443"),
        ],
    )
    def test_rewrites_url_to_pinned_ip_and_preserves_host_header(self, ip, expected_netloc):
        adapter = pr.PinnedIPAdapter()
        adapter.pin("Example.COM", ipaddress.ip_address(ip))
        request = requests.Request("GET", "https://example.com:8443/path?q=1").prepare()

        with patch.object(HTTPAdapter, "send", return_value=MagicMock()):
            adapter.send(request)

        assert request.url == f"https://{expected_netloc}/path?q=1"
        assert request.headers["Host"] == "example.com:8443"

    def test_unpinned_host_is_untouched(self):
        adapter = pr.PinnedIPAdapter()
        adapter.pin("example.com", ipaddress.ip_address("93.184.216.34"))
        request = requests.Request("GET", "https://other.example.org/path").prepare()

        with patch.object(HTTPAdapter, "send", return_value=MagicMock()):
            adapter.send(request)

        assert request.url == "https://other.example.org/path"
        assert "Host" not in request.headers
