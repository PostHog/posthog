"""Tests for the high-level eval labeling entry point (building agent inputs)."""

from typing import Any

import numpy as np

from posthog.temporal.llm_analytics.evaluation_clustering.data import EvaluationMetadata
from posthog.temporal.llm_analytics.evaluation_clustering.labeling import (
    _build_eval_cluster_data,
    _build_eval_contents,
    _derive_verdict,
)
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterItem, TraceLabelingMetadata


def _meta(eval_id: str, **kwargs) -> EvaluationMetadata:
    defaults: dict[str, Any] = {
        "eval_event_id": eval_id,
        "evaluation_id": "cfg-accuracy",
        "evaluation_name": "Accuracy",
        "evaluation_result": True,
        "evaluation_applicable": None,
        "evaluation_runtime": "llm_judge",
        "evaluation_reasoning": "reasoning text",
        "judge_cost_usd": 0.001,
        "target_generation_id": f"gen-{eval_id}",
        "target_trace_id": f"trace-{eval_id}",
        "generation_cost_usd": 0.01,
        "generation_latency_ms": 200.0,
        "generation_input_tokens": 500,
        "generation_output_tokens": 150,
        "generation_model": "gpt-4o",
        "generation_is_error": False,
    }
    defaults.update(kwargs)
    return EvaluationMetadata(**defaults)


class TestDeriveVerdict:
    def test_pass(self):
        assert _derive_verdict(_meta("e", evaluation_result=True, evaluation_applicable=None)) == "pass"

    def test_fail(self):
        assert _derive_verdict(_meta("e", evaluation_result=False, evaluation_applicable=None)) == "fail"

    def test_na_wins_over_result(self):
        assert _derive_verdict(_meta("e", evaluation_result=True, evaluation_applicable=False)) == "n/a"

    def test_applicable_true_keeps_result(self):
        assert _derive_verdict(_meta("e", evaluation_result=True, evaluation_applicable=True)) == "pass"

    def test_missing_meta(self):
        assert _derive_verdict(None) == "unknown"

    def test_missing_result_and_applicable(self):
        assert _derive_verdict(_meta("e", evaluation_result=None, evaluation_applicable=None)) == "unknown"


class TestBuildEvalContents:
    def test_keys_by_eval_id_from_generation_id_slot(self):
        items = [ClusterItem(trace_id="e1", generation_id="e1"), ClusterItem(trace_id="e2", generation_id="e2")]
        metadata = {"e1": _meta("e1"), "e2": _meta("e2", evaluation_result=False)}

        contents = _build_eval_contents(items, metadata)

        assert set(contents.keys()) == {"e1", "e2"}
        assert contents["e1"]["verdict"] == "pass"
        assert contents["e2"]["verdict"] == "fail"
        assert contents["e1"]["reasoning"] == "reasoning text"
        assert contents["e1"]["runtime"] == "llm_judge"

    def test_missing_metadata_uses_safe_defaults(self):
        items = [ClusterItem(trace_id="e1", generation_id="e1")]
        contents = _build_eval_contents(items, eval_metadata={})

        assert contents["e1"]["evaluation_name"] is None
        assert contents["e1"]["verdict"] == "unknown"
        assert contents["e1"]["reasoning"] is None


class TestBuildEvalClusterData:
    def test_splits_items_by_label_with_title_rendered(self):
        items = [
            ClusterItem(trace_id="e1", generation_id="e1"),
            ClusterItem(trace_id="e2", generation_id="e2"),
            ClusterItem(trace_id="e3", generation_id="e3"),
        ]
        labels = np.array([0, 0, 1])
        item_metadata = [
            TraceLabelingMetadata(x=0.1, y=0.2, distance_to_centroid=0.5, rank=1),
            TraceLabelingMetadata(x=0.15, y=0.25, distance_to_centroid=0.6, rank=2),
            TraceLabelingMetadata(x=1.0, y=1.0, distance_to_centroid=0.3, rank=1),
        ]
        centroid_coords_2d = [[0.125, 0.225], [1.0, 1.0]]
        metadata = {
            "e1": _meta("e1", evaluation_name="Accuracy", evaluation_result=True),
            "e2": _meta("e2", evaluation_name="Accuracy", evaluation_result=False),
            "e3": _meta("e3", evaluation_name="Tone", evaluation_result=True, evaluation_applicable=False),
        }

        result = _build_eval_cluster_data(
            items=items,
            labels=labels,
            item_metadata=item_metadata,
            centroid_coords_2d=centroid_coords_2d,
            unique_cluster_ids=np.array([0, 1]),
            eval_metadata=metadata,
        )

        assert set(result.keys()) == {0, 1}
        assert result[0]["size"] == 2
        assert result[1]["size"] == 1

        assert result[0]["evals"]["e1"]["title"] == "Accuracy: pass"
        assert result[0]["evals"]["e2"]["title"] == "Accuracy: fail"
        assert result[1]["evals"]["e3"]["title"] == "Tone: n/a"

    def test_centroid_falls_back_to_cluster_mean_when_coords_absent(self):
        items = [ClusterItem(trace_id="e1", generation_id="e1")]
        labels = np.array([0])
        item_metadata = [TraceLabelingMetadata(x=1.5, y=2.5, distance_to_centroid=0.0, rank=1)]

        result = _build_eval_cluster_data(
            items=items,
            labels=labels,
            item_metadata=item_metadata,
            centroid_coords_2d=[],  # no centroids provided
            unique_cluster_ids=np.array([0]),
            eval_metadata={"e1": _meta("e1")},
        )

        # Falls back to mean of the cluster's member coords
        assert result[0]["centroid_x"] == 1.5
        assert result[0]["centroid_y"] == 2.5
