import pytest
from unittest.mock import Mock, patch

import requests
from parameterized import parameterized

from posthog.temporal.data_imports.sources.convex.convex import (
    InvalidDeployUrlError,
    InvalidWindowError,
    _get_with_retry,
    document_deltas,
    get_json_schemas,
    list_snapshot,
    validate_credentials,
    validate_deploy_url,
)


class TestValidateDeployUrl:
    @parameterized.expand(
        [
            # valid — should normalize to clean https://host
            ("simple", "https://swift-lemur-123.convex.cloud", "https://swift-lemur-123.convex.cloud"),
            ("trailing_slash", "https://swift-lemur-123.convex.cloud/", "https://swift-lemur-123.convex.cloud"),
            ("uppercase", "HTTPS://Swift-Lemur-123.CONVEX.CLOUD", "https://swift-lemur-123.convex.cloud"),
            ("leading_space", "  https://swift-lemur-123.convex.cloud", "https://swift-lemur-123.convex.cloud"),
            ("with_path", "https://swift-lemur-123.convex.cloud/some/path", "https://swift-lemur-123.convex.cloud"),
            # invalid — should raise
            ("http", "http://swift-lemur-123.convex.cloud", None),
            ("ftp", "ftp://swift-lemur-123.convex.cloud", None),
            ("no_scheme", "swift-lemur-123.convex.cloud", None),
            ("wrong_tld", "https://swift-lemur-123.convex.io", None),
            ("extra_subdomain", "https://extra.swift-lemur-123.convex.cloud", None),
            ("lookalike", "https://convex.cloud.evil.com", None),
            ("bare_domain", "https://convex.cloud", None),
            ("ip_literal", "https://1.2.3.4", None),
            ("localhost", "https://localhost", None),
            ("metadata_ip", "https://169.254.169.254", None),
            ("internal_domain", "https://swift-lemur-123.convex.cloud.internal", None),
            ("query_params", "https://swift-lemur-123.convex.cloud?evil=1", None),
            ("fragment", "https://swift-lemur-123.convex.cloud#section", None),
        ]
    )
    def test_validate_deploy_url(self, _name, url, expected):
        if expected is not None:
            assert validate_deploy_url(url) == expected
        else:
            with pytest.raises(InvalidDeployUrlError):
                validate_deploy_url(url)

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_validate_credentials_rejects_bad_url_without_network_call(self, mock_get):
        ok, err = validate_credentials("http://169.254.169.254", "deploy-key")
        assert not ok
        assert err is not None
        mock_get.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_validate_credentials_accepts_valid_url(self, mock_get):
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        ok, err = validate_credentials("https://swift-lemur-123.convex.cloud", "prod:abc123")
        assert ok
        assert err is None
        called_url = mock_get.call_args.args[0]
        assert called_url.startswith("https://swift-lemur-123.convex.cloud/api/")


def _ok_response(payload: dict) -> Mock:
    response = Mock(status_code=200)
    response.json.return_value = payload
    response.raise_for_status = Mock()
    return response


def _proxy_error() -> requests.exceptions.ProxyError:
    return requests.exceptions.ProxyError("Remote end closed connection without response")


class TestGetWithRetry:
    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_retries_on_proxy_error_then_succeeds(self, mock_get):
        success = _ok_response({"ok": True})
        mock_get.side_effect = [_proxy_error(), _proxy_error(), success]

        _get_with_retry.retry.wait = lambda *_a, **_kw: 0  # type: ignore[attr-defined]

        response = _get_with_retry("https://swift-lemur-123.convex.cloud/api/json_schemas", timeout=1)
        assert response is success
        assert mock_get.call_count == 3

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_retries_on_502_then_succeeds(self, mock_get):
        transient = Mock(status_code=502)
        success = _ok_response({"ok": True})
        mock_get.side_effect = [transient, success]

        _get_with_retry.retry.wait = lambda *_a, **_kw: 0  # type: ignore[attr-defined]

        response = _get_with_retry("https://swift-lemur-123.convex.cloud/api/json_schemas", timeout=1)
        assert response is success
        assert mock_get.call_count == 2

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_does_not_retry_on_401(self, mock_get):
        unauthorized = Mock(status_code=401)
        unauthorized.json.return_value = {}
        mock_get.return_value = unauthorized

        response = _get_with_retry("https://swift-lemur-123.convex.cloud/api/json_schemas", timeout=1)
        assert response is unauthorized
        assert mock_get.call_count == 1

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_does_not_retry_on_400_invalid_window(self, mock_get):
        invalid_window = Mock(status_code=400)
        invalid_window.json.return_value = {"code": "InvalidWindowToReadDocuments"}
        mock_get.return_value = invalid_window

        response = _get_with_retry("https://swift-lemur-123.convex.cloud/api/document_deltas", timeout=1)
        assert response is invalid_window
        assert mock_get.call_count == 1

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_reraises_after_exhausting_retries(self, mock_get):
        mock_get.side_effect = _proxy_error()

        _get_with_retry.retry.wait = lambda *_a, **_kw: 0  # type: ignore[attr-defined]

        with pytest.raises(requests.exceptions.ProxyError):
            _get_with_retry("https://swift-lemur-123.convex.cloud/api/json_schemas", timeout=1)


class TestConvexCallsRetryHelper:
    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_get_json_schemas_uses_retry_layer(self, mock_get):
        mock_get.side_effect = [_proxy_error(), _ok_response({"users": {}})]

        _get_with_retry.retry.wait = lambda *_a, **_kw: 0  # type: ignore[attr-defined]

        result = get_json_schemas("https://swift-lemur-123.convex.cloud", "prod:abc")
        assert result == {"users": {}}
        assert mock_get.call_count == 2

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_list_snapshot_uses_retry_layer(self, mock_get):
        page = _ok_response({"values": [{"_id": "1"}], "snapshot": 42, "cursor": None, "hasMore": False})
        mock_get.side_effect = [_proxy_error(), page]

        _get_with_retry.retry.wait = lambda *_a, **_kw: 0  # type: ignore[attr-defined]

        gen = list_snapshot("https://swift-lemur-123.convex.cloud", "prod:abc", "users")
        batches = list(gen)
        assert batches == [[{"_id": "1"}]]
        assert mock_get.call_count == 2

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_document_deltas_uses_retry_layer(self, mock_get):
        page = _ok_response({"values": [{"_id": "1"}], "cursor": 100, "hasMore": False})
        mock_get.side_effect = [_proxy_error(), page]

        _get_with_retry.retry.wait = lambda *_a, **_kw: 0  # type: ignore[attr-defined]

        gen = document_deltas("https://swift-lemur-123.convex.cloud", "prod:abc", "users", cursor=0)
        batches = list(gen)
        assert batches == [[{"_id": "1"}]]
        assert mock_get.call_count == 2

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_document_deltas_invalid_window_is_not_retried(self, mock_get):
        invalid = Mock(status_code=400)
        invalid.json.return_value = {"code": "InvalidWindowToReadDocuments"}
        mock_get.return_value = invalid

        with pytest.raises(InvalidWindowError):
            list(document_deltas("https://swift-lemur-123.convex.cloud", "prod:abc", "users", cursor=0))
        assert mock_get.call_count == 1
