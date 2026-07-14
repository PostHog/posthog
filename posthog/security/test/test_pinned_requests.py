import ipaddress

import pytest
from unittest.mock import MagicMock, patch

import requests
from requests.adapters import HTTPAdapter

from posthog.security import pinned_requests as pr


def _redirect_response(status_code, location=None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"Location": location} if location else {}
    return response


class TestPinnedRequest:
    def test_blocked_url_raises_before_any_connection(self):
        with (
            patch.object(pr, "validate_url_and_pin_ips", return_value=(False, "Loopback host", set())),
            patch.object(pr.requests, "Session") as session_cls,
        ):
            with pytest.raises(pr.SSRFBlockedError, match="Loopback host"):
                pr.pinned_request("GET", "http://127.0.0.1/admin", timeout=5)
        session_cls.assert_not_called()

    def test_redirect_returned_as_is_by_default(self):
        with (
            patch.object(pr, "validate_url_and_pin_ips", return_value=(True, None, set())) as validate,
            patch.object(pr.requests, "Session") as session_cls,
        ):
            session_cls.return_value.request.return_value = _redirect_response(302, "http://127.0.0.1/admin")
            response = pr.pinned_request("GET", "https://example.com/x", timeout=5)
        assert response.status_code == 302
        assert validate.call_count == 1

    def test_follows_get_redirects_revalidating_each_hop(self):
        with (
            patch.object(pr, "validate_url_and_pin_ips", return_value=(True, None, set())) as validate,
            patch.object(pr.requests, "Session") as session_cls,
        ):
            session_cls.return_value.request.side_effect = [
                _redirect_response(302, "https://next.example.com/meta"),
                _redirect_response(200),
            ]
            response = pr.pinned_request("GET", "https://example.com/meta", timeout=5, max_redirects=3)
        assert response.status_code == 200
        assert validate.call_count == 2
        assert validate.call_args_list[1].args[0] == "https://next.example.com/meta"
        assert session_cls.return_value.request.call_args_list[1].args[1] == "https://next.example.com/meta"

    def test_redirect_to_blocked_target_raises(self):
        with (
            patch.object(
                pr,
                "validate_url_and_pin_ips",
                side_effect=[(True, None, set()), (False, "Disallowed target IP", set())],
            ),
            patch.object(pr.requests, "Session") as session_cls,
        ):
            session_cls.return_value.request.return_value = _redirect_response(302, "http://169.254.169.254/latest/")
            with pytest.raises(pr.SSRFBlockedError, match="Disallowed target IP"):
                pr.pinned_request("GET", "https://example.com/meta", timeout=5, max_redirects=3)

    def test_too_many_redirects_raises(self):
        with (
            patch.object(pr, "validate_url_and_pin_ips", return_value=(True, None, set())),
            patch.object(pr.requests, "Session") as session_cls,
        ):
            session_cls.return_value.request.return_value = _redirect_response(302, "https://example.com/loop")
            with pytest.raises(requests.TooManyRedirects):
                pr.pinned_request("GET", "https://example.com/meta", timeout=5, max_redirects=2)

    def test_non_get_refuses_redirect_following(self):
        with pytest.raises(ValueError, match="only supported for GET"):
            pr.pinned_request("POST", "https://example.com/register", timeout=5, max_redirects=1)


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
