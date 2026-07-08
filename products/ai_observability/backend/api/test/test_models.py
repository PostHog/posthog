from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from products.ai_observability.backend.api.models import LLMModelInfoSerializer, LLMModelsListResponseSerializer
from products.ai_observability.backend.llm import TRIAL_MODELS_BY_PROVIDER
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig


class TestLLMModelInfoSerializer(SimpleTestCase):
    def test_serializes_expected_shape(self):
        serializer = LLMModelInfoSerializer(data={"id": "gpt-4o-mini", "posthog_available": True})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {"id": "gpt-4o-mini", "posthog_available": True})

    def test_rejects_missing_fields(self):
        serializer = LLMModelInfoSerializer(data={"id": "gpt-4o-mini"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("posthog_available", serializer.errors)


class TestLLMModelsListResponseSerializer(SimpleTestCase):
    def test_serializes_nested_models(self):
        serializer = LLMModelsListResponseSerializer(
            data={
                "models": [
                    {"id": "gpt-4o-mini", "posthog_available": True},
                    {"id": "gpt-4o", "posthog_available": False},
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
        for entry in response.data["models"]:
            self.assertIn("posthog_available", entry)

    @parameterized.expand(
        [
            ("grandfathered", 50, True),
            ("terminal", 100, False),
        ]
    )
    @patch("products.ai_observability.backend.api.models.LLMModelConfiguration")
    def test_posthog_available_requires_grandfathering(self, _name, trial_evals_used, expected, mock_config_cls):
        # This flag feeds the MCP judge-models tool — a regression silently re-offers
        # PostHog-funded models to terminal teams via agents.
        trial_model = TRIAL_MODELS_BY_PROVIDER["openai"][0]
        mock_config_cls.return_value.get_available_models.return_value = [trial_model]
        with self.settings(AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE="2999-12-31T00:00:00+00:00"):
            EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=trial_evals_used)

            response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/models/?provider=openai")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["models"][0]["posthog_available"], expected)

    def test_unauthenticated_user_cannot_list_models(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/models/?provider=openai")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
