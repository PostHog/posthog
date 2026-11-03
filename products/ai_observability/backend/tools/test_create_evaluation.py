from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.provider_keys import LLMProviderKey
from products.ai_observability.backend.tools.create_evaluation import CreateEvaluationTool

from ee.hogai.tool_errors import MaxToolRetryableError


class TestCreateEvaluationTool(BaseTest):
    def _run(self, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        tool = CreateEvaluationTool(team=self.team, user=self.user)
        return async_to_sync(tool._arun_impl)(**kwargs)

    @parameterized.expand(
        [
            (
                "hog",
                {"evaluation_type": "hog", "source": "return true;"},
                {"source": "return true;"},
                {"allows_na": True},
                {},
            ),
            (
                "hog_trace_with_window",
                {
                    "evaluation_type": "hog",
                    "source": "return true;",
                    "target": "trace",
                    "window_seconds": 120,
                },
                {"source": "return true;"},
                {"allows_na": True},
                {"strategy": "fixed_window", "window_seconds": 120},
            ),
            (
                "hog_session_with_quiet_period",
                {
                    "evaluation_type": "hog",
                    "source": "return true;",
                    "target": "session",
                    "quiet_period_seconds": 900,
                },
                {"source": "return true;"},
                {"allows_na": True},
                {"strategy": "inactivity", "quiet_period_seconds": 900},
            ),
            ("sentiment", {"evaluation_type": "sentiment"}, {"source": "user_messages"}, {}, {}),
        ]
    )
    @patch("products.ai_observability.backend.api.evaluations.report_user_action")
    def test_creates_disabled_evaluation_tagged_as_posthog_ai(
        self,
        _name: str,
        args: dict[str, Any],
        expected_config: dict[str, Any],
        expected_output_config: dict[str, Any],
        expected_target_config: dict[str, Any],
        mock_report,
    ) -> None:
        content, artifact = self._run(name="Check", rollout_percentage=10, **args)

        evaluation = Evaluation.objects.get(id=artifact["evaluation_id"], team=self.team)
        assert evaluation.enabled is False
        assert expected_config.items() <= evaluation.evaluation_config.items()
        assert expected_output_config.items() <= evaluation.output_config.items()
        assert expected_target_config.items() <= (evaluation.target_config or {}).items()
        assert evaluation.conditions[0]["rollout_percentage"] == 10
        assert f"/ai-evals/evaluations/{evaluation.id}" in content
        assert mock_report.call_args.args[1] == "llma evaluation created"
        assert mock_report.call_args.args[2]["source"] == "posthog_ai"

    @parameterized.expand([("with_active_key", True), ("without_key", False)])
    def test_judge_uses_active_key_or_saves_a_keyless_draft(self, _name: str, has_key: bool) -> None:
        key = None
        if has_key:
            key = LLMProviderKey.objects.create(
                team=self.team,
                provider="anthropic",
                name="Key",
                state=LLMProviderKey.State.OK,
                encrypted_config={"api_key": "sk-ant-test"},
                created_by=self.user,
            )
            EvaluationConfig.objects.create(team=self.team, active_provider_key=key)

        content, artifact = self._run(name="Judge", evaluation_type="llm_judge", prompt="Did it answer?")

        model_configuration = Evaluation.objects.get(id=artifact["evaluation_id"], team=self.team).model_configuration
        assert model_configuration is not None
        expected_provider = "anthropic" if has_key else "openai"
        assert model_configuration.provider == expected_provider
        assert model_configuration.model == DEFAULT_MODEL_BY_PROVIDER[expected_provider]
        assert model_configuration.provider_key_id == (key.id if key else None)
        assert ("no provider API key" in content) is not has_key

    @parameterized.expand(
        [
            ("hog_without_source", {"evaluation_type": "hog"}),
            ("judge_without_prompt", {"evaluation_type": "llm_judge"}),
            ("sentiment_on_trace", {"evaluation_type": "sentiment", "target": "trace"}),
            ("hog_that_fails_to_compile", {"evaluation_type": "hog", "source": "return (;"}),
        ]
    )
    def test_rejects_invalid_evaluations_without_saving(self, _name: str, args: dict[str, Any]) -> None:
        with pytest.raises(MaxToolRetryableError):
            self._run(name="Bad", **args)
        assert not Evaluation.objects.filter(team=self.team).exists()
