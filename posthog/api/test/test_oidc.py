from unittest.mock import Mock, patch

from django.test import SimpleTestCase

import requests
from requests.structures import CaseInsensitiveDict
from social_core.exceptions import AuthConnectionError

from posthog.api.oidc import OIDC_FETCH_MAX_BYTES, MultitenantOIDCAuth


class TestMultitenantOIDCAuthRequest(SimpleTestCase):
    def test_streams_and_closes_response_after_bounded_read(self) -> None:
        response = requests.Response()
        response.status_code = 200
        response.headers = CaseInsensitiveDict({"Content-Type": "application/json"})
        response.iter_content = Mock(return_value=iter([b'{"issuer": "https://idp.example.com"}']))
        response.close = Mock()
        session = Mock()
        session.request.return_value = response
        auth = object.__new__(MultitenantOIDCAuth)

        with patch("posthog.api.oidc.pinned_session") as pinned_session:
            pinned_session.return_value.__enter__.return_value = session
            result = auth.request("https://idp.example.com/discovery")

        assert result.json() == {"issuer": "https://idp.example.com"}
        request_kwargs = session.request.call_args.kwargs
        assert request_kwargs["stream"] is True
        assert request_kwargs["allow_redirects"] is False
        connect_timeout, read_timeout = request_kwargs["timeout"]
        assert 0 < connect_timeout <= 10
        assert 0 < read_timeout <= 10
        response.close.assert_called_once()

    def test_rejects_response_that_exceeds_byte_limit_while_streaming(self) -> None:
        response = requests.Response()
        response.status_code = 200
        response.headers = CaseInsensitiveDict()
        response.iter_content = Mock(return_value=iter([b"x" * OIDC_FETCH_MAX_BYTES, b"y"]))
        response.close = Mock()
        session = Mock()
        session.request.return_value = response
        auth = object.__new__(MultitenantOIDCAuth)

        with patch("posthog.api.oidc.pinned_session") as pinned_session:
            pinned_session.return_value.__enter__.return_value = session
            with self.assertRaises(AuthConnectionError):
                auth.request("https://idp.example.com/discovery")

        response.close.assert_called_once()
