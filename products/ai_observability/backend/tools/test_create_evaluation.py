from posthog.test.base import BaseTest

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluation_configs import EvaluationType, OutputType
from products.ai_observability.backend.models.evaluations import Evaluation, EvaluationStatus
from products.ai_observability.backend.models.provider_keys import LLMProviderKey
from products.ai_observability.backend.tools.create_evaluation import CreateEvaluationTool

HOG_SOURCE = "return length(output) > 10;"


def _run_tool(tool, **kwargs):
    return async_to_sync(tool._arun_impl)(**kwargs)


class TestCreateEvaluationTool(BaseTest):
    def _make_tool(self):
        return CreateEvaluationTool(team=self.team, user=self.user)

    def _add_active_provider_key(self, provider="openai", state=LLMProviderKey.State.OK):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider=provider,
            name="Active key",
            state=state,
            encrypted_config={"api_key": "sk-test"},
            created_by=self.user,
        )
        EvaluationConfig.objects.create(team=self.team, active_provider_key=key)
        return key

    def test_hog_evaluation_is_saved_paused_with_compiled_bytecode(self):
        content, _ = _run_tool(
            self._make_tool(),
            name="Output is long enough",
            evaluation_type="hog",
            source=HOG_SOURCE,
        )

        evaluation = Evaluation.objects.get(team=self.team)
        assert evaluation.evaluation_type == EvaluationType.HOG
        assert evaluation.output_type == OutputType.BOOLEAN
        assert evaluation.evaluation_config["source"] == HOG_SOURCE
        assert evaluation.evaluation_config["bytecode"]
        assert evaluation.enabled is False
        assert evaluation.status == EvaluationStatus.PAUSED
        assert evaluation.created_by == self.user
        assert str(evaluation.id) in content

    def test_enabled_hog_evaluation_starts_active(self):
        _run_tool(
            self._make_tool(),
            name="Output is long enough",
            evaluation_type="hog",
            source=HOG_SOURCE,
            enabled=True,
        )

        evaluation = Evaluation.objects.get(team=self.team)
        assert evaluation.enabled is True
        assert evaluation.status == EvaluationStatus.ACTIVE

    def test_uncompilable_hog_source_creates_nothing(self):
        content, _ = _run_tool(
            self._make_tool(),
            name="Broken",
            evaluation_type="hog",
            source="this is not hog",
        )

        assert "Could not save the evaluation" in content
        assert not Evaluation.objects.filter(team=self.team).exists()

    def test_llm_judge_defaults_to_the_teams_active_key_provider(self):
        self._add_active_provider_key(provider="anthropic")

        _run_tool(
            self._make_tool(),
            name="Answer cites a source",
            evaluation_type="llm_judge",
            prompt="Pass when the answer cites a source.",
        )

        evaluation = Evaluation.objects.get(team=self.team)
        assert evaluation.model_configuration is not None
        assert evaluation.model_configuration.provider == "anthropic"
        assert evaluation.model_configuration.model

    def test_llm_judge_without_any_provider_key_creates_nothing(self):
        content, _ = _run_tool(
            self._make_tool(),
            name="Answer cites a source",
            evaluation_type="llm_judge",
            prompt="Pass when the answer cites a source.",
        )

        assert "provider" in content
        assert not Evaluation.objects.filter(team=self.team).exists()

    def test_enabling_an_llm_judge_without_a_working_key_saves_it_paused(self):
        self._add_active_provider_key(state=LLMProviderKey.State.INVALID)

        content, _ = _run_tool(
            self._make_tool(),
            name="Answer cites a source",
            evaluation_type="llm_judge",
            prompt="Pass when the answer cites a source.",
            enabled=True,
        )

        evaluation = Evaluation.objects.get(team=self.team)
        assert evaluation.enabled is False
        assert "Saved paused" in content

    @parameterized.expand(
        [
            ("fixed_window", {"window_seconds": 120}, {"strategy": "fixed_window", "window_seconds": 120}),
            (
                "inactivity",
                {"quiet_period_seconds": 300, "max_age_seconds": 3600},
                {"strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 3600},
            ),
        ]
    )
    def test_trace_target_settle_config(self, _name, kwargs, expected):
        _run_tool(
            self._make_tool(),
            name="Trace eval",
            evaluation_type="hog",
            source=HOG_SOURCE,
            target="trace",
            **kwargs,
        )

        evaluation = Evaluation.objects.get(team=self.team)
        assert evaluation.target == "trace"
        assert evaluation.target_config == expected

    def test_generation_target_carries_no_settle_config(self):
        _run_tool(
            self._make_tool(),
            name="Generation eval",
            evaluation_type="hog",
            source=HOG_SOURCE,
        )

        assert Evaluation.objects.get(team=self.team).target_config == {}

    def test_sentiment_cannot_target_traces(self):
        content, _ = _run_tool(
            self._make_tool(),
            name="Sentiment",
            evaluation_type="sentiment",
            target="trace",
        )

        assert "generation" in content
        assert not Evaluation.objects.filter(team=self.team).exists()

    def test_filters_and_sampling_become_one_condition_set(self):
        _run_tool(
            self._make_tool(),
            name="Scoped eval",
            evaluation_type="hog",
            source=HOG_SOURCE,
            property_filters=[{"key": "$ai_model", "value": ["gpt-4"], "operator": "exact", "type": "event"}],
            rollout_percentage=10,
        )

        conditions = Evaluation.objects.get(team=self.team).conditions
        assert len(conditions) == 1
        assert conditions[0]["rollout_percentage"] == 10
        assert conditions[0]["properties"][0]["key"] == "$ai_model"

    def test_unscoped_evaluation_has_no_conditions(self):
        _run_tool(
            self._make_tool(),
            name="Everything",
            evaluation_type="hog",
            source=HOG_SOURCE,
        )

        assert Evaluation.objects.get(team=self.team).conditions == []

    @parameterized.expand([("paused", False, False), ("enabled", True, True)])
    def test_only_starting_an_evaluation_needs_approval(self, _name, enabled, expected):
        tool = self._make_tool()
        assert async_to_sync(tool.is_dangerous_operation)(enabled=enabled) is expected
