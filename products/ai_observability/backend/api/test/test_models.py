from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from products.ai_observability.backend.api.models import (
    SUPPORTED_PROVIDERS,
    LLMModelInfoSerializer,
    LLMModelsListResponseSerializer,
)
from products.ai_observability.backend.models.provider_keys import LLMProviderKey


class TestLLMModelInfoSerializer(SimpleTestCase):
    def test_serializes_expected_shape(self):
        serializer = LLMModelInfoSerializer(data={"id": "gpt-4o-mini", "provider": "openai"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {"id": "gpt-4o-mini", "provider": "openai"})

    def test_rejects_missing_id(self):
        serializer = LLMModelInfoSerializer(data={})
        self.assertFalse(serializer.is_valid())
        self.assertIn("id", serializer.errors)


class TestLLMModelsListResponseSerializer(SimpleTestCase):
    def test_serializes_nested_models(self):
        serializer = LLMModelsListResponseSerializer(
            data={
                "models": [
                    {"id": "gpt-4o-mini", "provider": "openai"},
                    {"id": "gpt-4o", "provider": "openai"},
                ],
                "providers": [{"provider": "openai", "model_count": 2, "requires_provider_key": False}],
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(len(serializer.validated_data["models"]), 2)
        self.assertEqual(serializer.validated_data["models"][0]["id"], "gpt-4o-mini")
        self.assertEqual(serializer.validated_data["providers"][0]["model_count"], 2)


class TestLLMModelsViewSet(APIBaseTest):
    def _list(self, query: str = "") -> Any:
        return self.client.get(f"/api/environments/{self.team.id}/llm_analytics/models/{query}")

    def test_lists_every_supported_provider_when_provider_is_omitted(self):
        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual([entry["provider"] for entry in body["providers"]], SUPPORTED_PROVIDERS)
        # `model_count` is what an agent reads to decide whether a provider is worth pursuing, so it
        # has to agree with what `models` actually holds for that provider.
        self.assertTrue(all(model["provider"] in SUPPORTED_PROVIDERS for model in body["models"]))
        for entry in body["providers"]:
            listed = [model for model in body["models"] if model["provider"] == entry["provider"]]
            self.assertEqual(len(listed), entry["model_count"])

    def test_provider_summary_flags_providers_whose_models_need_a_key(self):
        body = self._list().json()

        needs_key = {entry["provider"] for entry in body["providers"] if entry["requires_provider_key"]}
        self.assertTrue(needs_key, "expected at least one provider to be BYOK-only")
        # A flagged provider is expected to contribute no models until a key is supplied, which is
        # what the flag exists to explain.
        self.assertEqual([model for model in body["models"] if model["provider"] in needs_key], [])
        self.assertTrue(
            {entry["provider"] for entry in body["providers"] if not entry["requires_provider_key"]},
            "expected at least one provider PostHog funds models for",
        )

    @patch("products.ai_observability.backend.api.models.LLMModelConfiguration")
    def test_returns_models_for_valid_provider(self, mock_config_cls):
        mock_config_cls.return_value.get_available_models.return_value = ["gpt-4o-mini", "gpt-4o"]

        response = self._list("?provider=openai")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual([m["id"] for m in body["models"]], ["gpt-4o-mini", "gpt-4o"])
        self.assertEqual([m["provider"] for m in body["models"]], ["openai", "openai"])
        self.assertEqual(body["providers"], [{"provider": "openai", "model_count": 2, "requires_provider_key": False}])

    @patch("products.ai_observability.backend.api.models.LLMModelConfiguration")
    def test_key_id_alone_resolves_the_provider_from_the_key(self, mock_config_cls):
        mock_config_cls.return_value.get_available_models.return_value = ["claude-sonnet-4-5"]
        key = LLMProviderKey.objects.create(team=self.team, provider="anthropic", name="team key")

        response = self._list(f"?key_id={key.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["models"], [{"id": "claude-sonnet-4-5", "provider": "anthropic"}])
        self.assertEqual([entry["provider"] for entry in body["providers"]], ["anthropic"])
        self.assertEqual(mock_config_cls.call_args.kwargs["provider_key"], key)

    def test_rejects_key_id_that_belongs_to_another_provider(self):
        key = LLMProviderKey.objects.create(team=self.team, provider="anthropic", name="team key")

        response = self._list(f"?provider=openai&key_id={key.id}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        detail = response.json()["detail"]
        self.assertIn("anthropic", detail)
        # A key resolves its own provider, so the rejection has to name that as the way out.
        self.assertIn("omit the provider param", detail.lower())

    @parameterized.expand(
        [
            ("unknown_uuid", "019f5632-6df1-0000-5093-46d18b1bc987"),
            # A key_id the ORM can't parse as a UUID reaches the query builder as a ValidationError,
            # which would otherwise surface as a 500 rather than a missing key.
            ("malformed_uuid", "not-a-uuid"),
        ]
    )
    def test_unknown_key_id_returns_404(self, _name, key_id):
        response = self._list(f"?key_id={key_id}")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("provider key", response.json()["detail"])

    def test_rejects_invalid_provider(self):
        response = self._list("?provider=not-a-real-provider")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        detail = response.json()["detail"]
        self.assertIn("invalid provider", detail.lower())
        # The rejection has to name the way out, or an agent asking for the catalog retries the same call.
        self.assertIn("omit the provider param", detail.lower())

    def test_unauthenticated_user_cannot_list_models(self):
        self.client.logout()
        response = self._list("?provider=openai")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
