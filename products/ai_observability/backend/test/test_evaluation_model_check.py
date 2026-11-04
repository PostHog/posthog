from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.ai_observability.backend.llm.errors import (
    ModelNotFoundError,
    ModelPermissionError,
    ProviderConnectionError,
    UnsupportedModelError,
)
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.model_configuration import LLMModelConfiguration
from products.ai_observability.backend.models.provider_keys import LLMProviderKey
from products.ai_observability.backend.tasks.evaluation_model_check import check_evaluation_model


class TestCheckEvaluationModel(BaseTest):
    def _judge(self) -> Evaluation:
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test"},
            created_by=self.user,
        )
        model_configuration = LLMModelConfiguration.objects.create(
            team=self.team, provider="openai", model="gpt-4o", provider_key=key
        )
        return Evaluation.objects.create(
            team=self.team,
            name="Judge",
            enabled=True,
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test"},
            output_type="boolean",
            model_configuration=model_configuration,
        )

    @parameterized.expand(
        [
            ("model_answers", None, "active", None),
            ("model_not_found", ModelNotFoundError("gpt-4o"), "error", "model_not_found"),
            ("model_not_supported", UnsupportedModelError("gpt-4o"), "error", "model_not_supported"),
            ("key_lacks_access", ModelPermissionError("gpt-4o"), "error", "provider_key_permission_denied"),
            ("provider_unreachable", ProviderConnectionError("down"), "active", None),
        ]
    )
    def test_a_model_the_key_cannot_use_errors_the_evaluation(self, _name, error, status, reason) -> None:
        evaluation = self._judge()

        with patch("products.ai_observability.backend.llm.client.Client.complete", side_effect=error):
            check_evaluation_model(self.team.id, str(evaluation.id), "openai", "gpt-4o")

        evaluation.refresh_from_db()
        self.assertEqual((evaluation.status, evaluation.status_reason), (status, reason))

    def test_a_model_changed_during_the_check_is_left_alone(self) -> None:
        evaluation = self._judge()

        with patch(
            "products.ai_observability.backend.llm.client.Client.complete", side_effect=ModelNotFoundError("gpt-4o")
        ):
            check_evaluation_model(self.team.id, str(evaluation.id), "openai", "gpt-4o-old")

        evaluation.refresh_from_db()
        self.assertEqual(evaluation.status, "active")
