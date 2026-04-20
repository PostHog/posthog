import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.convex.convex import (
    InvalidDeployUrlError,
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
