import re

from posthog.test.base import BaseTest

from products.autoresearch.backend.models import AutoresearchPipeline
from products.autoresearch.backend.training import build_agent_description


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
        prompt = build_agent_description(pipeline=pipeline, iteration_budget=5, training_run_id="run-123")
        # `{anchors}` and `{lookback_days}` are intentional — they are documented
        # placeholders the agent is taught to use inside its own SQL. Anything
        # else with single-curly-braces is a Python interpolation bug.
        permitted = {"{anchors}", "{lookback_days}"}
        candidates = set(re.findall(r"\{[a-z_][a-z0-9_]*\}", prompt))
        leftover = candidates - permitted
        assert leftover == set(), f"unresolved interpolations in prompt: {leftover}"

    def test_prompt_includes_pipeline_specifics(self) -> None:
        pipeline = self._make_pipeline()
        prompt = build_agent_description(pipeline=pipeline, iteration_budget=5, training_run_id="run-123")
        assert pipeline.target_event in prompt
        assert str(pipeline.horizon_days) in prompt
        assert str(pipeline.pk) in prompt
        # The training run id is injected so the agent can address the nested tools.
        assert "run-123" in prompt
        # Step 3 is the sandbox fit/eval loop.
        assert "fit and evaluate" in prompt
        assert "roc_auc_score" in prompt

    def test_prompt_drives_materialize_features_not_execute_sql_pull(self) -> None:
        pipeline = self._make_pipeline()
        prompt = build_agent_description(pipeline=pipeline, iteration_budget=5, training_run_id="run-123")
        # New data path: the agent materializes feature parquet via the tool and reads it with pandas.
        assert "autoresearch-materialize-features" in prompt
        assert "train_features_path" in prompt
        assert "read_parquet" in prompt
        # The legacy execute-sql composite-pull + DataFrame(rows) path must be gone.
        assert "pd.DataFrame(rows)" not in prompt
        assert "labeled_anchors" not in prompt

    def test_prompt_drives_artifact_bundle_flow_not_set_output(self) -> None:
        pipeline = self._make_pipeline()
        prompt = build_agent_description(pipeline=pipeline, iteration_budget=5, training_run_id="run-123")
        # New flow: upload a runnable bundle + finalize. The legacy set_output/recipe.json
        # path must be gone from the prompt.
        assert "autoresearch-training-runs-artifacts-upload-create" in prompt
        assert "autoresearch-training-runs-complete-create" in prompt
        assert "train.py" in prompt and "predict.py" in prompt and "features.sql" in prompt
        # The legacy curl-to-set_output submission and recipe.json must be gone.
        assert "set_output/" not in prompt
        assert "recipe.json" not in prompt

    def test_prompt_instructs_report_md(self) -> None:
        pipeline = self._make_pipeline()
        prompt = build_agent_description(pipeline=pipeline, iteration_budget=5, training_run_id="run-123")
        # The agent must author a portable report.md, uploaded like the bundle files, with charts.
        assert "report.md" in prompt
        assert "mermaid" in prompt
        assert "autoresearch-training-runs-artifacts-upload-create" in prompt
