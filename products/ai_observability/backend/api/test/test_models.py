from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from rest_framework import status

from products.ai_observability.backend.api.models import LLMModelInfoSerializer, LLMModelsListResponseSerializer
from products.ai_observability.backend.models.provider_keys import LLMProviderKey


class TestLLMModelInfoSerializer(SimpleTestCase):
    def test_serializes_expected_shape(self):
        serializer = LLMModelInfoSerializer(data={"id": "gpt-4o-mini"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {"id": "gpt-4o-mini"})

    def test_rejects_missing_id(self):
        serializer = LLMModelInfoSerializer(data={})
        self.assertFalse(serializer.is_valid())
        self.assertIn("id", serializer.errors)


class TestLLMModelsListResponseSerializer(SimpleTestCase):
    def test_serializes_nested_models(self):
        serializer = LLMModelsListResponseSerializer(
            data={
                "models": [
                    {"id": "gpt-4o-mini"},
                    {"id": "gpt-4o"},
                ]
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(len(serializer.validated_data["models"]), 2)
        self.assertEqual(serializer.validated_data["models"][0]["id"], "gpt-4o-mini")


class TestLLMModelsViewSet(APIBaseTest):
    def test_requires_provider_query_param(self):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/models/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("provider", response.data["detail"].lower())

    def test_rejects_invalid_provider(self):
        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_analytics/models/?provider=not-a-real-provider"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("invalid provider", response.data["detail"].lower())

    @patch("products.ai_observability.backend.api.models.LLMModelConfiguration")
    def test_returns_models_for_valid_provider(self, mock_config_cls):
        mock_config_cls.return_value.get_available_models.return_value = ["gpt-4o-mini", "gpt-4o"]

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/models/?provider=openai")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("models", response.data)
        returned_ids = [m["id"] for m in response.data["models"]]
        self.assertEqual(returned_ids, ["gpt-4o-mini", "gpt-4o"])

    @patch("products.ai_observability.backend.llm.client.Client.list_models")
    def test_key_scoped_listing_forwards_provider_config(self, mock_list_models):
        mock_list_models.return_value = ["qwen3-max"]
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai_compatible",
            name="Custom endpoint",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "custom-key-123", "base_url": "https://8.8.8.8/v1"},
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_analytics/models/?provider=openai_compatible&key_id={key.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([m["id"] for m in response.data["models"]], ["qwen3-max"])
        # Without the forwarded base_url the adapter cannot reach the endpoint and returns [].
        mock_list_models.assert_called_once_with("openai_compatible", "custom-key-123", base_url="https://8.8.8.8/v1")

    def test_unauthenticated_user_cannot_list_models(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/models/?provider=openai")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
