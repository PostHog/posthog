from types import SimpleNamespace
from typing import Any, cast

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

import requests
from requests.structures import CaseInsensitiveDict
from social_core.exceptions import AuthConnectionError

from posthog.api.oidc import OIDC_FETCH_MAX_BYTES, OIDC_FETCH_TIMEOUT_SECONDS, MultitenantOIDCAuth
from posthog.models import IdentityProviderConfig


class TestMultitenantOIDCAuthRequest(SimpleTestCase):
    def test_streams_and_closes_response_after_bounded_read(self) -> None:
        response = requests.Response()
        response.status_code = 200
        response.headers = CaseInsensitiveDict({"Content-Type": "application/json"})
        cast(Any, response).iter_content = Mock(return_value=iter([b'{"issuer": "https://idp.example.com"}']))
        cast(Any, response).close = Mock()
        session = Mock()
        session.request.return_value = response
        auth = object.__new__(MultitenantOIDCAuth)
        auth.identity_provider_config = cast(IdentityProviderConfig, SimpleNamespace(id=123, organization_id=456))

        with patch("posthog.api.oidc.pinned_session") as pinned_session:
            pinned_session.return_value.__enter__.return_value = session
            result = auth.request("https://idp.example.com/discovery")

        assert result.json() == {"issuer": "https://idp.example.com"}
        request_kwargs = session.request.call_args.kwargs
        assert request_kwargs["stream"] is True
        assert request_kwargs["allow_redirects"] is False
        timeout = request_kwargs["timeout"]
        assert timeout.total == OIDC_FETCH_TIMEOUT_SECONDS
        assert timeout.connect_timeout <= OIDC_FETCH_TIMEOUT_SECONDS
        assert timeout.read_timeout <= OIDC_FETCH_TIMEOUT_SECONDS
        response.close.assert_called_once()

    def test_rejects_response_that_exceeds_byte_limit_while_streaming(self) -> None:
        response = requests.Response()
        response.status_code = 200
        response.headers = CaseInsensitiveDict()
        cast(Any, response).iter_content = Mock(return_value=iter([b"x" * OIDC_FETCH_MAX_BYTES, b"y"]))
        cast(Any, response).close = Mock()
        session = Mock()
        session.request.return_value = response
        auth = object.__new__(MultitenantOIDCAuth)
        auth.identity_provider_config = cast(IdentityProviderConfig, SimpleNamespace(id=123, organization_id=456))

        with patch("posthog.api.oidc.pinned_session") as pinned_session:
            pinned_session.return_value.__enter__.return_value = session
            with patch("posthog.api.oidc.logger") as logger:
                with self.assertRaises(AuthConnectionError):
                    auth.request("https://idp.example.com/.well-known/openid-configuration")

        response.close.assert_called_once()
        logger.warning.assert_called_once_with(
            "oidc_request_failed",
            phase="discovery",
            failure_category="response_too_large",
            identity_provider_config_id="123",
            organization_id="456",
            duration_seconds=logger.warning.call_args.kwargs["duration_seconds"],
        )
