"""Tests for the evaluation labeling agent tools and graph."""

import json

from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage

from posthog.temporal.llm_analytics.evaluation_clustering.labeling_agent.graph import (
    _apply_fallbacks,
    run_eval_labeling_agent,
)
from posthog.temporal.llm_analytics.evaluation_clustering.labeling_agent.state import (
    ClusterEvalData,
    EvalContent,
    EvalMetadata,
)
from posthog.temporal.llm_analytics.evaluation_clustering.labeling_agent.tools import (
    bulk_set_labels,
    finalize_labels,
    get_all_clusters_with_sample_titles,
    get_cluster_eval_titles,
    get_clusters_overview,
    get_current_labels,
    get_eval_reasoning,
    set_cluster_label,
)
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel


def _sample_state() -> dict:
    """Build a small state snapshot the agent's tools can read."""
    cluster_data: dict[int, ClusterEvalData] = {
        0: ClusterEvalData(
            cluster_id=0,
            size=2,
            centroid_x=0.1,
            centroid_y=0.2,
            evals={
                "e1": EvalMetadata(
                    eval_id="e1", title="Accuracy: pass", rank=1, distance_to_centroid=0.3, x=0.0, y=0.0
                ),
                "e2": EvalMetadata(
                    eval_id="e2", title="Accuracy: fail", rank=2, distance_to_centroid=0.5, x=0.1, y=0.1
                ),
            },
        ),
        1: ClusterEvalData(
            cluster_id=1,
            size=1,
            centroid_x=1.0,
            centroid_y=1.0,
            evals={
                "e3": EvalMetadata(eval_id="e3", title="Tone: n/a", rank=1, distance_to_centroid=0.0, x=1.0, y=1.0),
            },
        ),
    }
    contents: dict[str, EvalContent] = {
        "e1": EvalContent(
            evaluation_id="eval-accuracy",
            evaluation_name="Accuracy",
            verdict="pass",
            reasoning="Answer was correct",
            runtime="llm_judge",
            generation_model="gpt-4o",
            is_error=False,
            judge_cost_usd=0.001,
            target_generation_id="gen-1",
        ),
        "e2": EvalContent(
            evaluation_id="eval-accuracy",
            evaluation_name="Accuracy",
            verdict="fail",
            reasoning="Missed the detail",
            runtime="llm_judge",
            generation_model="gpt-4o",
            is_error=False,
            judge_cost_usd=0.002,
            target_generation_id="gen-2",
        ),
        "e3": EvalContent(
            evaluation_id="eval-tone",
            evaluation_name="Tone",
            verdict="n/a",
            reasoning="Out of scope",
            runtime="hog",
            generation_model=None,
            is_error=None,
            judge_cost_usd=None,
            target_generation_id=None,
        ),
    }
    return {
        "team_id": 1,
        "cluster_data": cluster_data,
        "all_eval_contents": contents,
        "current_labels": {},
    }


class TestEvalLabelingTools:
    def test_overview_lists_clusters(self):
        state = _sample_state()
        result = json.loads(get_clusters_overview.invoke({"state": state}))
        assert {c["cluster_id"] for c in result} == {0, 1}
        cluster_0 = next(c for c in result if c["cluster_id"] == 0)
        assert cluster_0["size"] == 2

    def test_all_clusters_with_sample_titles_renders_titles(self):
        state = _sample_state()
        result = json.loads(get_all_clusters_with_sample_titles.invoke({"state": state, "titles_per_cluster": 10}))

        cluster_0 = next(c for c in result if c["cluster_id"] == 0)
        # Titles come from EvalMetadata.title, ordered by rank
        assert cluster_0["sample_titles"] == ["Accuracy: pass", "Accuracy: fail"]

        cluster_1 = next(c for c in result if c["cluster_id"] == 1)
        assert cluster_1["sample_titles"] == ["Tone: n/a"]

    def test_get_cluster_eval_titles_limits_and_sorts(self):
        state = _sample_state()
        result = json.loads(get_cluster_eval_titles.invoke({"state": state, "cluster_id": 0, "limit": 10}))
        # Rank 1 comes first
        assert result[0]["rank"] == 1
        assert result[0]["title"] == "Accuracy: pass"

    def test_get_cluster_eval_titles_missing_cluster_returns_empty(self):
        state = _sample_state()
        result = json.loads(get_cluster_eval_titles.invoke({"state": state, "cluster_id": 99, "limit": 10}))
        assert result == []

    def test_get_eval_reasoning_returns_full_content(self):
        state = _sample_state()
        result = json.loads(get_eval_reasoning.invoke({"state": state, "eval_ids": ["e1", "e3"]}))
        by_id = {d["eval_id"]: d for d in result}
        assert by_id["e1"]["reasoning"] == "Answer was correct"
        assert by_id["e1"]["verdict"] == "pass"
        assert by_id["e1"]["generation_model"] == "gpt-4o"
        assert by_id["e3"]["runtime"] == "hog"
        assert by_id["e3"]["generation_model"] is None

    def test_get_eval_reasoning_skips_unknown_ids(self):
        state = _sample_state()
        result = json.loads(get_eval_reasoning.invoke({"state": state, "eval_ids": ["missing", "e1"]}))
        assert len(result) == 1
        assert result[0]["eval_id"] == "e1"

    def test_set_cluster_label_mutates_state(self):
        state = _sample_state()
        set_cluster_label.invoke(
            {
                "state": state,
                "cluster_id": 0,
                "title": "Factuality failures",
                "description": "- bullet",
            }
        )
        assert isinstance(state["current_labels"][0], ClusterLabel)
        assert state["current_labels"][0].title == "Factuality failures"

    def test_bulk_set_labels(self):
        state = _sample_state()
        bulk_set_labels.invoke(
            {
                "state": state,
                "labels": [
                    {"cluster_id": 0, "title": "c0", "description": "- d0"},
                    {"cluster_id": 1, "title": "c1", "description": "- d1"},
                ],
            }
        )
        assert state["current_labels"][0].title == "c0"
        assert state["current_labels"][1].title == "c1"

    def test_get_current_labels_reflects_state(self):
        state = _sample_state()
        state["current_labels"][0] = ClusterLabel(title="t", description="d")
        result = json.loads(get_current_labels.invoke({"state": state}))
        assert result["0"] == {"title": "t", "description": "d"}
        assert result["1"] is None

    def test_finalize_reports_progress(self):
        state = _sample_state()
        state["current_labels"][0] = ClusterLabel(title="t", description="d")
        out = finalize_labels.invoke({"state": state})
        assert "1/2" in out


class TestApplyFallbacks:
    def test_preserves_existing_labels(self):
        cluster_data = {
            0: ClusterEvalData(cluster_id=0, size=5, centroid_x=0, centroid_y=0, evals={}),
            1: ClusterEvalData(cluster_id=1, size=3, centroid_x=0, centroid_y=0, evals={}),
        }
        existing: dict[int, ClusterLabel | None] = {0: ClusterLabel(title="kept", description="bullet")}
        result = _apply_fallbacks(existing, cluster_data)
        assert result[0].title == "kept"
        assert result[1].title == "Cluster 1"
        assert "3 similar evaluations" in result[1].description

    def test_noise_cluster_gets_eval_flavoured_outlier_copy(self):
        cluster_data = {
            -1: ClusterEvalData(cluster_id=-1, size=2, centroid_x=0, centroid_y=0, evals={}),
        }
        result = _apply_fallbacks({}, cluster_data)
        assert result[-1].title == "Outliers"
        assert "evaluation" in result[-1].description.lower()


class TestRunEvalLabelingAgent:
    @patch("posthog.temporal.llm_analytics.evaluation_clustering.labeling_agent.graph.get_labeling_llm")
    @patch("posthog.temporal.llm_analytics.evaluation_clustering.labeling_agent.graph.create_react_agent")
    def test_runs_agent_and_returns_labels(self, mock_create_agent, mock_get_labeling_llm):
        mock_get_labeling_llm.return_value = MagicMock()
        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_agent.invoke.return_value = {
            "messages": [HumanMessage(content="done")],
            "current_labels": {0: ClusterLabel(title="Agent-produced", description="- desc")},
        }

        cluster_data = {
            0: ClusterEvalData(cluster_id=0, size=5, centroid_x=0, centroid_y=0, evals={}),
            1: ClusterEvalData(cluster_id=1, size=3, centroid_x=0, centroid_y=0, evals={}),
        }

        result = run_eval_labeling_agent(
            team_id=1,
            cluster_data=cluster_data,
            all_eval_contents={},
            window_start="2026-04-15T00:00:00Z",
            window_end="2026-04-16T00:00:00Z",
        )

        assert result[0].title == "Agent-produced"
        assert result[1].title == "Cluster 1"  # filled by fallback
        mock_create_agent.assert_called_once()

    @patch("posthog.temporal.llm_analytics.evaluation_clustering.labeling_agent.graph.get_labeling_llm")
    @patch("posthog.temporal.llm_analytics.evaluation_clustering.labeling_agent.graph.create_react_agent")
    def test_handles_agent_error_gracefully(self, mock_create_agent, mock_get_labeling_llm):
        mock_get_labeling_llm.return_value = MagicMock()
        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_agent.invoke.side_effect = Exception("LLM error")

        cluster_data = {0: ClusterEvalData(cluster_id=0, size=5, centroid_x=0, centroid_y=0, evals={})}

        result = run_eval_labeling_agent(
            team_id=1,
            cluster_data=cluster_data,
            all_eval_contents={},
            window_start="2026-04-15T00:00:00Z",
            window_end="2026-04-16T00:00:00Z",
        )
        # Fallback kicks in; test must not raise
        assert result[0].title == "Cluster 0"
