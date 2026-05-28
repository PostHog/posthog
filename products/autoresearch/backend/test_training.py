import re

from posthog.test.base import BaseTest

from products.autoresearch.backend.models import AutoresearchPipeline
from products.autoresearch.backend.training import _resolve_labeled_anchors_cte_for_prompt, build_agent_description


class TestResolveLabeledAnchorsCte(BaseTest):
    """
    The agent's inner loop depends on pasting this CTE block verbatim into
    execute-sql. Any unresolved placeholder, dangling f-string brace, or
    structural drift breaks every iteration silently.
    """

    def _make_pipeline(self, **kwargs) -> AutoresearchPipeline:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "name": "Test",
            "target_event": "$pageview",
            "horizon_days": 7,
            "training_lookback_days": 180,
            "iteration_budget": 10,
            "iteration_budget_remaining": 10,
        }
        defaults.update(kwargs)
        return AutoresearchPipeline.objects.create(**defaults)

    def test_resolved_cte_has_no_unresolved_placeholders(self) -> None:
        pipeline = self._make_pipeline()
        cte = _resolve_labeled_anchors_cte_for_prompt(pipeline)
        # Any leftover {key} placeholder = broken paste-in for the agent.
        leftover = re.findall(r"\{[a-z_][a-z0-9_]*\}", cte)
        assert leftover == [], f"unresolved placeholders in agent CTE: {leftover}"

    def test_resolved_cte_contains_pipeline_values(self) -> None:
        pipeline = self._make_pipeline(target_event="signed_up", horizon_days=14, training_lookback_days=90)
        cte = _resolve_labeled_anchors_cte_for_prompt(pipeline)
        assert "'signed_up'" in cte
        assert "toIntervalDay(14)" in cte
        assert "toIntervalDay(90)" in cte
        assert "labeled_users" in cte
        assert "labeled_anchors" in cte

    def test_resolved_cte_with_training_population_filter(self) -> None:
        pipeline = self._make_pipeline(
            training_population={"properties": [{"key": "email", "type": "person", "operator": "is_set"}]},
        )
        cte = _resolve_labeled_anchors_cte_for_prompt(pipeline)
        # The is_set operator emits AND (isNotNull(...) AND ...) — agent CTE
        # must include this so local iteration matches the trainer's view.
        assert "person.properties.email" in cte
        assert "isNotNull" in cte
        leftover = re.findall(r"\{[a-z_][a-z0-9_]*\}", cte)
        assert leftover == [], f"unresolved placeholders with population filter: {leftover}"


class TestBuildAgentDescription(BaseTest):
    """
    Smoke-tests that the agent prompt renders without leftover f-string braces
    or missing template variables. The prompt is huge; broken interpolations
    silently produce literal "{var}" in the agent's instructions.
    """

    def _make_pipeline(self) -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test pipeline",
            target_event="$pageview",
            horizon_days=7,
            training_lookback_days=180,
            iteration_budget=10,
            iteration_budget_remaining=10,
        )

    def test_prompt_renders_without_unresolved_placeholders(self) -> None:
        pipeline = self._make_pipeline()
        prompt = build_agent_description(pipeline=pipeline, iteration_budget=5)
        # `{anchors}` and `{lookback_days}` are intentional — they are documented
        # placeholders the agent is taught to use inside its own SQL. Anything
        # else with single-curly-braces is a Python interpolation bug.
        permitted = {"{anchors}", "{lookback_days}"}
        candidates = set(re.findall(r"\{[a-z_][a-z0-9_]*\}", prompt))
        leftover = candidates - permitted
        assert leftover == set(), f"unresolved interpolations in prompt: {leftover}"

    def test_prompt_includes_pipeline_specifics(self) -> None:
        pipeline = self._make_pipeline()
        prompt = build_agent_description(pipeline=pipeline, iteration_budget=5)
        assert pipeline.target_event in prompt
        assert str(pipeline.horizon_days) in prompt
        assert str(pipeline.pk) in prompt
        # The "Step 3 — Fit and evaluate" section is the new sandbox loop.
        assert "Fit and evaluate" in prompt
        assert "roc_auc_score" in prompt
        # Old corr() heuristic should be gone.
        assert "0.5 + 0.25 × Σ|corr_i|" not in prompt
