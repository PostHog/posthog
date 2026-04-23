"""Unit tests for Stage B per-cluster aggregate computation."""

import pytest

from parameterized import parameterized

from posthog.temporal.llm_analytics.evaluation_clustering.aggregates import aggregate_evaluation_metrics
from posthog.temporal.llm_analytics.evaluation_clustering.data import EvaluationMetadata


def _meta(
    eval_id: str,
    *,
    name: str | None = "Accuracy",
    result: bool | None = True,
    applicable: bool | None = None,
    runtime: str | None = "llm_judge",
    reasoning: str | None = "ok",
    judge_cost: float | None = 0.001,
    gen_cost: float | None = 0.01,
    gen_latency: float | None = 200.0,
    gen_in_tokens: int | None = 500,
    gen_out_tokens: int | None = 150,
    gen_model: str | None = "gpt-4o",
    gen_error: bool | None = False,
) -> EvaluationMetadata:
    return EvaluationMetadata(
        eval_event_id=eval_id,
        evaluation_id=f"cfg-{name or 'unknown'}",
        evaluation_name=name,
        evaluation_result=result,
        evaluation_applicable=applicable,
        evaluation_runtime=runtime,
        evaluation_reasoning=reasoning,
        judge_cost_usd=judge_cost,
        target_generation_id=f"gen-{eval_id}",
        target_trace_id=f"trace-{eval_id}",
        generation_cost_usd=gen_cost,
        generation_latency_ms=gen_latency,
        generation_input_tokens=gen_in_tokens,
        generation_output_tokens=gen_out_tokens,
        generation_model=gen_model,
        generation_is_error=gen_error,
    )


class TestAggregateEvaluationMetrics:
    def test_partitions_by_cluster_label(self):
        eval_ids = ["e1", "e2", "e3", "e4"]
        labels = [0, 0, 1, 1]
        metadata = {eid: _meta(eid) for eid in eval_ids}

        result = aggregate_evaluation_metrics(eval_ids, labels, metadata)

        assert set(result.keys()) == {0, 1}
        assert result[0].item_count == 2
        assert result[1].item_count == 2

    @parameterized.expand(
        [
            # (verdicts: list of (result, applicable), expected pass_rate, na_rate)
            ("all_pass", [(True, None), (True, None), (True, None)], 1.0, 0.0),
            ("all_fail", [(False, None), (False, None)], 0.0, 0.0),
            ("half_pass", [(True, None), (False, None)], 0.5, 0.0),
            ("with_na", [(True, None), (True, False), (False, None)], 1 / 3, 1 / 3),
            ("applicable_true_keeps_verdict", [(True, True), (False, True)], 0.5, 0.0),
        ]
    )
    def test_pass_rate_and_na_rate(self, _name, verdicts, expected_pass, expected_na):
        eval_ids = [f"e{i}" for i in range(len(verdicts))]
        metadata = {
            eid: _meta(eid, result=result, applicable=applicable)
            for eid, (result, applicable) in zip(eval_ids, verdicts)
        }

        result = aggregate_evaluation_metrics(eval_ids, labels=[0] * len(eval_ids), metadata=metadata)

        assert result[0].pass_rate == pytest.approx(expected_pass)
        assert result[0].na_rate == pytest.approx(expected_na)

    def test_dominant_evaluation_name(self):
        eval_ids = ["e1", "e2", "e3"]
        metadata = {
            "e1": _meta("e1", name="Accuracy"),
            "e2": _meta("e2", name="Accuracy"),
            "e3": _meta("e3", name="Tone"),
        }
        result = aggregate_evaluation_metrics(eval_ids, [0, 0, 0], metadata)
        assert result[0].dominant_evaluation_name == "Accuracy"

    def test_dominant_runtime(self):
        eval_ids = ["e1", "e2", "e3"]
        metadata = {
            "e1": _meta("e1", runtime="llm_judge"),
            "e2": _meta("e2", runtime="hog"),
            "e3": _meta("e3", runtime="hog"),
        }
        result = aggregate_evaluation_metrics(eval_ids, [0, 0, 0], metadata)
        assert result[0].dominant_runtime == "hog"

    def test_avg_judge_cost_ignores_zero_and_none(self):
        eval_ids = ["e1", "e2", "e3", "e4"]
        metadata = {
            "e1": _meta("e1", judge_cost=0.002),
            "e2": _meta("e2", judge_cost=0.004),
            "e3": _meta("e3", judge_cost=0.0),  # excluded
            "e4": _meta("e4", judge_cost=None),  # excluded
        }
        result = aggregate_evaluation_metrics(eval_ids, [0, 0, 0, 0], metadata)
        assert result[0].avg_judge_cost == pytest.approx(0.003)

    def test_missing_linked_generation_degrades_gracefully(self):
        """Evals whose linked generation was purged still count toward eval-specific metrics."""
        eval_ids = ["e1", "e2"]
        metadata = {
            "e1": _meta("e1"),
            "e2": _meta(
                "e2",
                gen_cost=None,
                gen_latency=None,
                gen_in_tokens=None,
                gen_out_tokens=None,
                gen_model=None,
                gen_error=None,
            ),
        }
        result = aggregate_evaluation_metrics(eval_ids, [0, 0], metadata)

        # Both count toward eval-specific tallies
        assert result[0].pass_rate == 1.0
        assert result[0].item_count == 2

        # Only e1's generation data drives operational averages
        assert result[0].avg_cost == pytest.approx(0.01)
        assert result[0].avg_latency == pytest.approx(200.0)

    def test_error_rate_only_counts_evals_with_operational_data(self):
        eval_ids = ["e1", "e2", "e3"]
        metadata = {
            "e1": _meta("e1", gen_error=True),
            "e2": _meta("e2", gen_error=False),
            "e3": _meta(
                "e3",
                gen_cost=None,
                gen_latency=None,
                gen_in_tokens=None,
                gen_out_tokens=None,
                gen_model=None,
                gen_error=None,
            ),
        }
        result = aggregate_evaluation_metrics(eval_ids, [0, 0, 0], metadata)

        # 1 of 2 evals-with-operational-data errored; e3 is excluded from the rate
        assert result[0].error_rate == pytest.approx(0.5)
        assert result[0].error_count == 1

    def test_metadata_missing_entirely_drops_to_zero_metrics(self):
        """When an eval is in labels but absent from metadata, don't crash."""
        eval_ids = ["e1"]
        result = aggregate_evaluation_metrics(eval_ids, [0], metadata={})

        assert result[0].item_count == 1
        assert result[0].pass_rate is None
        assert result[0].avg_cost is None
        assert result[0].dominant_evaluation_name is None
