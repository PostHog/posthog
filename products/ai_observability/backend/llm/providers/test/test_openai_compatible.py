import pytest
from unittest.mock import MagicMock, patch

import httpx
import openai
from parameterized import parameterized

from posthog.security.pinned_httpx import PinnedIPHTTPTransport
from posthog.security.pinned_requests import SSRFBlockedError

from products.ai_observability.backend.llm.providers import openai_compatible
from products.ai_observability.backend.llm.providers.openai_compatible import (
    DISALLOWED_BASE_URL_MESSAGE,
    REDIRECT_MESSAGE,
    OpenAICompatibleAdapter,
    error_field_for_validation_message,
    is_allowed_custom_base_url,
)
from products.ai_observability.backend.llm.types import AnalyticsContext, CompletionRequest

# A public IP literal keeps the DNS-resolution check offline in tests.
ALLOWED_BASE_URL = "https://8.8.8.8/v1"

OPENAI_PATCH_TARGET = "products.ai_observability.backend.llm.providers.openai_compatible.openai.OpenAI"


def _completion_request() -> CompletionRequest:
    return CompletionRequest(
        model="some-model",
        messages=[{"role": "user", "content": "hi"}],
        provider="openai_compatible",
    )


class TestIsAllowedCustomBaseUrl:
    @parameterized.expand(
        [
            ("empty", ""),
            ("no_hostname", "https://"),
            ("http_scheme", "http://8.8.8.8/v1"),
            ("private_ip", "https://10.0.0.1/v1"),
            ("loopback", "https://127.0.0.1/v1"),
            ("cloud_metadata", "https://169.254.169.254/latest"),
            ("ipv6_loopback", "https://[::1]/v1"),
        ]
    )
    def test_disallowed_base_urls(self, _name, base_url):
        assert is_allowed_custom_base_url(base_url) is False

    def test_public_https_base_url_is_allowed(self):
        assert is_allowed_custom_base_url(ALLOWED_BASE_URL) is True


class TestErrorFieldForValidationMessage:
    @parameterized.expand(
        [
            ("required", "Base URL is required", "base_url"),
            ("disallowed", DISALLOWED_BASE_URL_MESSAGE, "base_url"),
            ("not_found", "The endpoint did not return a model list, check the base URL", "base_url"),
            ("redirect", REDIRECT_MESSAGE, "base_url"),
            ("connection", "Could not connect to the endpoint", "base_url"),
            ("bad_key", "Invalid API key", "api_key"),
            ("unattributed", "Rate limited, please try again later", None),
            ("none", None, None),
        ]
    )
    def test_maps_message_to_field(self, _name, message, expected_field):
        assert error_field_for_validation_message(message) == expected_field


class TestPinnedHttpClient:
    def test_client_is_locked_to_the_validated_endpoint(self):
        with openai_compatible._pinned_http_client(ALLOWED_BASE_URL) as client:
            # Following a redirect would reach a host nothing validated, and the hop would be
            # made by the pooled connection rather than a freshly validated one.
            assert client.follow_redirects is False
            assert isinstance(client._transport, PinnedIPHTTPTransport)

            with pytest.raises(SSRFBlockedError):
                client.get("https://internal.example/v1/models")


class TestOpenAICompatibleAdapter:
    @patch(OPENAI_PATCH_TARGET)
    def test_validate_key_uses_configured_base_url(self, mock_openai):
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_openai.return_value = mock_client

        state, message = OpenAICompatibleAdapter.validate_key("test-key", base_url=ALLOWED_BASE_URL)

        assert state == "ok"
        assert message is None
        assert mock_openai.call_args.kwargs["base_url"] == ALLOWED_BASE_URL

    @patch(OPENAI_PATCH_TARGET)
    def test_validate_key_without_base_url_is_invalid(self, mock_openai):
        state, message = OpenAICompatibleAdapter.validate_key("test-key")

        assert state == "invalid"
        assert message == "Base URL is required"
        mock_openai.assert_not_called()

    @patch(OPENAI_PATCH_TARGET)
    def test_validate_key_with_disallowed_base_url_is_invalid(self, mock_openai):
        state, message = OpenAICompatibleAdapter.validate_key("test-key", base_url="https://10.0.0.1/v1")

        assert state == "invalid"
        assert message == DISALLOWED_BASE_URL_MESSAGE
        mock_openai.assert_not_called()

    @patch(OPENAI_PATCH_TARGET)
    def test_list_models_uses_configured_base_url(self, mock_openai):
        model = MagicMock()
        model.id = "qwen3-max"
        model.created = 1700000000

        mock_client = MagicMock()
        mock_client.models.list.return_value = [model]
        mock_openai.return_value = mock_client

        models = OpenAICompatibleAdapter.list_models("test-key", base_url=ALLOWED_BASE_URL)

        assert models == ["qwen3-max"]
        assert mock_openai.call_args.kwargs["base_url"] == ALLOWED_BASE_URL

    @patch(OPENAI_PATCH_TARGET)
    def test_list_models_handles_endpoints_that_omit_created(self, mock_openai):
        # Endpoints are free to leave `created` out, and the SDK turns that into None. Sorting
        # those raises a TypeError that the adapter would swallow into an empty model list.
        undated, dated = MagicMock(), MagicMock()
        undated.id, undated.created = "no-timestamp", None
        dated.id, dated.created = "timestamped", 1700000000
        mock_openai.return_value.models.list.return_value = [undated, dated]

        assert OpenAICompatibleAdapter.list_models("test-key", base_url=ALLOWED_BASE_URL) == [
            "timestamped",
            "no-timestamp",
        ]

    @patch(OPENAI_PATCH_TARGET)
    def test_list_models_without_key_returns_empty(self, mock_openai):
        assert OpenAICompatibleAdapter.list_models(None, base_url=ALLOWED_BASE_URL) == []
        mock_openai.assert_not_called()

    @patch(OPENAI_PATCH_TARGET)
    def test_list_models_with_disallowed_base_url_returns_empty(self, mock_openai):
        assert OpenAICompatibleAdapter.list_models("test-key", base_url="https://169.254.169.254/v1") == []
        mock_openai.assert_not_called()

    @parameterized.expand(
        [
            ("unconfigured", ""),
            ("private_ip", "https://10.0.0.1/v1"),
        ]
    )
    def test_complete_refuses_disallowed_base_url(self, _name, base_url):
        adapter = OpenAICompatibleAdapter(base_url=base_url)

        with pytest.raises(ValueError, match="Base URL must be"):
            adapter.complete(_completion_request(), "test-key", AnalyticsContext())

    def test_stream_refuses_disallowed_base_url(self):
        adapter = OpenAICompatibleAdapter(base_url="")

        with pytest.raises(ValueError, match="Base URL must be"):
            list(adapter.stream(_completion_request(), "test-key", AnalyticsContext()))

    @patch(OPENAI_PATCH_TARGET)
    def test_validate_key_reports_a_redirect_instead_of_following_it(self, mock_openai):
        redirect = openai.APIStatusError(
            "redirect",
            response=httpx.Response(302, request=httpx.Request("GET", f"{ALLOWED_BASE_URL}/models")),
            body=None,
        )
        mock_openai.return_value.models.list.side_effect = redirect

        state, message = OpenAICompatibleAdapter.validate_key("test-key", base_url=ALLOWED_BASE_URL)

        assert state == "invalid"
        assert message == REDIRECT_MESSAGE

    @patch(OPENAI_PATCH_TARGET)
    def test_validate_key_is_invalid_when_the_host_fails_pinning(self, mock_openai):
        # Stands in for a record that resolved publicly during validation and rebinds to a
        # private address before the request goes out.
        with patch.object(openai_compatible, "pinned_transport", side_effect=SSRFBlockedError("Internal IP")):
            state, message = OpenAICompatibleAdapter.validate_key("test-key", base_url=ALLOWED_BASE_URL)

        assert state == "invalid"
        assert message == DISALLOWED_BASE_URL_MESSAGE
        mock_openai.assert_not_called()

    @patch(OPENAI_PATCH_TARGET)
    def test_complete_without_api_key_raises(self, mock_openai):
        adapter = OpenAICompatibleAdapter(base_url=ALLOWED_BASE_URL)

        with pytest.raises(ValueError, match="BYOKEY-only"):
            adapter.complete(_completion_request(), None, AnalyticsContext())
        mock_openai.assert_not_called()
