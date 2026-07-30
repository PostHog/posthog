from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.request import Request

from posthog.rate_limit import (
    LLMProxyBurstRateThrottle,
    LLMProxyBYOKBurstRateThrottle,
    LLMProxyBYOKDailyRateThrottle,
    LLMProxyBYOKSustainedRateThrottle,
    LLMProxyDailyRateThrottle,
    LLMProxySustainedRateThrottle,
)

from products.ai_observability.backend.api.proxy import LLMProxyCompletionSerializer, LLMProxyViewSet
from products.ai_observability.backend.llm import (
    PLAYGROUND_MODEL_IDS,
    PROVIDERS,
    get_default_models,
    get_playground_models,
)
from products.ai_observability.backend.models.provider_keys import LLMProviderKey

PLAYGROUND_THROTTLES = (LLMProxyBurstRateThrottle, LLMProxySustainedRateThrottle, LLMProxyDailyRateThrottle)
BYOK_THROTTLES = (LLMProxyBYOKBurstRateThrottle, LLMProxyBYOKSustainedRateThrottle, LLMProxyBYOKDailyRateThrottle)


class TestLLMProxyThrottles(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.current_team = self.team
        self.viewset = LLMProxyViewSet()

    def _completion_payload(self, provider_key_id: str | None = None, provider: str = "openai") -> dict:
        payload: dict = {
            "system": "",
            "messages": [{"role": "user", "content": "hello"}],
            "model": "gpt-4.1-mini",
            "provider": provider,
        }
        if provider_key_id is not None:
            payload["provider_key_id"] = provider_key_id
        return payload

    def _set_request(self, action: str, data: dict) -> None:
        self.viewset.action = action
        self.viewset.request = cast(Request, SimpleNamespace(data=data, user=self.user))

    # Params: (provider_key_id, key_provider, encrypted_config, request_provider, has_team, expected_throttles)
    @parameterized.expand(
        [
            ("no_provider_key", None, "openai", None, "openai", True, PLAYGROUND_THROTTLES),
            ("invalid_provider_key_id", str(uuid4()), "openai", None, "openai", True, PLAYGROUND_THROTTLES),
            ("provider_key_without_api_key", "generated", "openai", {}, "openai", True, PLAYGROUND_THROTTLES),
            (
                "valid_matching_provider_key",
                "generated",
                "openai",
                {"api_key": "sk-test-key"},
                "openai",
                True,
                BYOK_THROTTLES,
            ),
            (
                "valid_together_byok_key",
                "generated",
                "together_ai",
                {"api_key": "together-key"},
                "together_ai",
                True,
                BYOK_THROTTLES,
            ),
            (
                "valid_openrouter_byok_key",
                "generated",
                "openrouter",
                {"api_key": "sk-or-key"},
                "openrouter",
                True,
                BYOK_THROTTLES,
            ),
            (
                "valid_fireworks_byok_key",
                "generated",
                "fireworks",
                {"api_key": "fw-key"},
                "fireworks",
                True,
                BYOK_THROTTLES,
            ),
            (
                "provider_mismatch_key_anthropic_req_openai",
                "generated",
                "anthropic",
                {"api_key": "sk-ant-key"},
                "openai",
                True,
                BYOK_THROTTLES,
            ),
            (
                "provider_mismatch_key_openai_req_anthropic",
                "generated",
                "openai",
                {"api_key": "sk-key"},
                "anthropic",
                True,
                BYOK_THROTTLES,
            ),
            (
                "user_without_team",
                "generated",
                "openai",
                {"api_key": "sk-test-key"},
                "openai",
                False,
                PLAYGROUND_THROTTLES,
            ),
        ]
    )
    def test_completion_throttle_behavior(
        self,
        _name: str,
        provider_key_id,
        key_provider,
        encrypted_config,
        request_provider: str,
        has_team: bool,
        expected_throttles: tuple,
    ) -> None:
        if not has_team:
            self.user.current_team = None

        if provider_key_id == "generated":
            key = LLMProviderKey.objects.create(
                team=self.team,
                provider=key_provider,
                name="Test key",
                encrypted_config=encrypted_config,
                created_by=self.user,
            )
            provider_key_id = str(key.id)

        self._set_request("completion", self._completion_payload(provider_key_id, provider=request_provider))

        throttles = self.viewset.get_throttles()

        assert len(throttles) == len(expected_throttles)
        for throttle, expected_cls in zip(throttles, expected_throttles):
            assert isinstance(throttle, expected_cls)

    def test_models_endpoint_is_never_throttled(self) -> None:
        self._set_request("models", {})
        assert self.viewset.get_throttles() == []

    def test_completion_serializer_accepts_sampling_settings(self) -> None:
        serializer = LLMProxyCompletionSerializer(
            data={
                "system": "You are helpful.",
                "messages": [{"role": "user", "content": "Hello"}],
                "model": "gpt-5-mini",
                "provider": "openai",
                "temperature": 0.4,
                "top_p": 0.9,
                "seed": 42,
            }
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["temperature"] == 0.4
        assert serializer.validated_data["top_p"] == 0.9
        assert serializer.validated_data["seed"] == 42


class TestPlaygroundModelAllowlist(TestCase):
    def test_playground_models_are_subset_of_supported_models(self) -> None:
        for _, config in PROVIDERS:
            assert set(config.PLAYGROUND_MODELS) <= set(config.SUPPORTED_MODELS), (
                f"{config.__name__}.PLAYGROUND_MODELS contains models not in SUPPORTED_MODELS"
            )

    def test_model_ids_unique_across_providers(self) -> None:
        all_playground: list[str] = []
        for _, config in PROVIDERS:
            all_playground.extend(config.PLAYGROUND_MODELS)
        assert len(all_playground) == len(set(all_playground)), "Duplicate model IDs found across providers"

    def test_get_playground_models_returns_only_playground_eligible(self) -> None:
        playground_ids = {m["id"] for m in get_playground_models()}
        assert playground_ids == PLAYGROUND_MODEL_IDS

    def test_get_playground_models_smaller_than_default(self) -> None:
        assert len(get_playground_models()) < len(get_default_models())


class TestPlaygroundModelEnforcement(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.customer_id = "cus_test"
        self.organization.save()

    def _completion_payload(self, model: str, provider: str) -> dict:
        return {
            "system": "",
            "messages": [{"role": "user", "content": "hi"}],
            "model": model,
            "provider": provider,
        }

    @parameterized.expand(
        [
            ("expensive_openai", "gpt-5.4", "openai"),
            ("expensive_anthropic", "claude-opus-4-6", "anthropic"),
        ]
    )
    def test_completion_rejects_non_playground_model(self, _name: str, model: str, provider: str) -> None:
        response = self.client.post(
            "/api/llm_proxy/completion/",
            data=self._completion_payload(model, provider),
            format="json",
        )
        assert response.status_code == 403
        assert "not available on the PostHog-funded playground" in response.json()["error"]

    @patch("products.ai_observability.backend.api.proxy.Client")
    def test_completion_allows_playground_model(self, mock_client_cls) -> None:
        mock_client_cls.return_value.stream.return_value = iter([])
        response = self.client.post(
            "/api/llm_proxy/completion/",
            data=self._completion_payload("gpt-4.1-mini", "openai"),
            format="json",
        )
        assert response.status_code == 200
        # Consume the streaming response to trigger the generator
        b"".join(response.streaming_content)  # type: ignore[attr-defined]
        mock_client_cls.return_value.stream.assert_called_once()

    @patch("products.ai_observability.backend.api.proxy.Client")
    def test_byok_key_bypasses_playground_allowlist(self, mock_client_cls) -> None:
        mock_client_cls.return_value.stream.return_value = iter([])
        byok_key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="BYOK key",
            encrypted_config={"api_key": "sk-test-key"},
            created_by=self.user,
        )
        payload = self._completion_payload("gpt-5.4", "openai")
        payload["provider_key_id"] = str(byok_key.id)
        response = self.client.post(
            "/api/llm_proxy/completion/",
            data=payload,
            format="json",
        )
        assert response.status_code == 200
        # Consume the streaming response to trigger the generator
        b"".join(response.streaming_content)  # type: ignore[attr-defined]
        mock_client_cls.return_value.stream.assert_called_once()

    def test_models_endpoint_returns_only_playground_models(self) -> None:
        response = self.client.get("/api/llm_proxy/models/")
        assert response.status_code == 200
        returned_ids = {m["id"] for m in response.json()}
        assert returned_ids == PLAYGROUND_MODEL_IDS
