from django.test import SimpleTestCase

import httpx
import openai
from parameterized import parameterized

from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ContextWindowExceededError,
    LLMError,
    ModelNotFoundError,
    ModelPermissionError,
    ProviderConnectionError,
    ProviderMismatchError,
    QuotaExceededError,
    RateLimitError,
    StructuredOutputParseError,
    UnsupportedModelError,
    UnsupportedProviderError,
    user_facing_error_message,
)

GENERIC_MESSAGE = "The request to the model provider failed. Try again."


class TestLLMErrors(SimpleTestCase):
    def test_llm_error_is_exception(self):
        error = LLMError("test error")
        assert isinstance(error, Exception)
        assert str(error) == "test error"

    def test_unsupported_model_error(self):
        error = UnsupportedModelError("gpt-99")
        assert error.model == "gpt-99"
        assert "gpt-99" in str(error)
        assert isinstance(error, LLMError)

    def test_unsupported_provider_error(self):
        error = UnsupportedProviderError("unknown_provider")
        assert error.provider == "unknown_provider"
        assert "unknown_provider" in str(error)
        assert isinstance(error, LLMError)

    def test_authentication_error(self):
        error = AuthenticationError("Invalid API key")
        assert "Invalid API key" in str(error)
        assert isinstance(error, LLMError)

    def test_rate_limit_error(self):
        error = RateLimitError("Too many requests")
        assert isinstance(error, LLMError)

    def test_quota_exceeded_error(self):
        error = QuotaExceededError("Quota exceeded")
        assert isinstance(error, LLMError)

    def test_provider_mismatch_error(self):
        error = ProviderMismatchError("openai", "anthropic")
        assert error.key_provider == "openai"
        assert error.request_provider == "anthropic"
        assert "openai" in str(error)
        assert "anthropic" in str(error)
        assert isinstance(error, LLMError)

    def test_model_not_found_error(self):
        error = ModelNotFoundError("gpt-99")
        assert error.model == "gpt-99"
        assert "gpt-99" in str(error)
        assert "not found" in str(error).lower()
        assert isinstance(error, LLMError)

    def test_model_permission_error_with_model(self):
        error = ModelPermissionError("gpt-4o")
        assert error.model == "gpt-4o"
        assert "gpt-4o" in str(error)
        assert "access" in str(error).lower()
        assert isinstance(error, LLMError)

    def test_model_permission_error_without_model(self):
        error = ModelPermissionError()
        assert error.model is None
        assert "access" in str(error).lower()
        assert isinstance(error, LLMError)


class TestErrorHierarchy(SimpleTestCase):
    @parameterized.expand(
        [
            (UnsupportedModelError("test"),),
            (UnsupportedProviderError("test"),),
            (AuthenticationError("test"),),
            (RateLimitError("test"),),
            (QuotaExceededError("test"),),
            (ProviderMismatchError("a", "b"),),
            (ModelNotFoundError("test"),),
            (ModelPermissionError("test"),),
        ]
    )
    def test_all_errors_inherit_from_llm_error(self, error):
        assert isinstance(error, LLMError)
        assert isinstance(error, Exception)

    @parameterized.expand(
        [
            (UnsupportedModelError("test"),),
            (UnsupportedProviderError("test"),),
            (AuthenticationError("test"),),
            (RateLimitError("test"),),
            (QuotaExceededError("test"),),
            (ProviderMismatchError("a", "b"),),
            (ModelNotFoundError("test"),),
            (ModelPermissionError("test"),),
        ]
    )
    def test_errors_can_be_caught_as_llm_error(self, error):
        caught = False
        try:
            raise error
        except LLMError:
            caught = True
        assert caught


class TestUserFacingErrorMessage(SimpleTestCase):
    @parameterized.expand(
        [
            (ModelNotFoundError("gpt-4-turbo"),),
            (UnsupportedModelError("gpt-99"),),
            (UnsupportedProviderError("cohere"),),
            (ModelPermissionError("o3-pro"),),
            (ModelPermissionError(),),
            (ProviderMismatchError("openai", "anthropic"),),
            (AuthenticationError("401"),),
            (QuotaExceededError("insufficient_quota"),),
            (RateLimitError("429"),),
            (ContextWindowExceededError("too long"),),
            (ProviderConnectionError("reset by peer"),),
            (StructuredOutputParseError("bad json"),),
        ]
    )
    def test_every_error_in_the_taxonomy_gets_its_own_copy(self, error):
        assert user_facing_error_message(error) != GENERIC_MESSAGE

    @parameterized.expand(
        [
            (ModelNotFoundError("gpt-4-turbo"),),
            (UnsupportedModelError("gpt-99"),),
            (ModelPermissionError("o3-pro"),),
        ]
    )
    def test_copy_about_a_model_names_the_model(self, error):
        assert error.model in user_facing_error_message(error)

    def test_unmapped_provider_error_keeps_the_providers_reason(self):
        # A 400 caused by the request itself — an unsupported parameter, a malformed tool schema —
        # has no branch in the taxonomy, and retrying it can only fail the same way. The provider's
        # own sentence is the only actionable thing left, so it has to survive.
        detail = "Unsupported value: 'temperature' does not support 0.7 with this model."
        body = {"error": {"message": detail}}
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        error = openai.BadRequestError(
            f"Error code: 400 - {body}",
            response=httpx.Response(status_code=400, request=request, json=body),
            body=body,
        )

        message = user_facing_error_message(error)

        assert detail in message
        assert "Error code: 400" not in message

    def test_google_style_error_exposes_its_reason_through_the_message_attribute(self):
        # google-genai puts the text on `message` rather than in a parsed `body`.
        class FakeAPIError(Exception):
            message = "models/gemini-1.0-pro is not found for API version v1beta"

        assert "models/gemini-1.0-pro is not found" in user_facing_error_message(FakeAPIError())

    @parameterized.expand([(None,), (RuntimeError("boom"),), (ValueError(""),)])
    def test_error_with_no_readable_reason_falls_back_to_the_generic_message(self, error):
        assert user_facing_error_message(error) == GENERIC_MESSAGE
