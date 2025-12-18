"""Tests for the cluster labeling agent."""

import json

from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage

from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.graph import (
    _fill_missing_labels,
    run_labeling_agent,
)
from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.state import ClusterTraceData
from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.tools import (
    bulk_set_labels,
    finalize_labels,
    get_all_clusters_with_sample_titles,
    get_cluster_trace_titles,
    get_clusters_overview,
    get_current_labels,
    get_trace_details,
    set_cluster_label,
)
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel


def make_test_state(
    cluster_data: dict | None = None,
    trace_summaries: dict | None = None,
    current_labels: dict | None = None,
) -> dict:
    """Create a test state dict for tool testing."""
    if cluster_data is None:
        cluster_data = {
            0: ClusterTraceData(
                cluster_id=0,
                size=3,
                centroid_x=1.0,
                centroid_y=2.0,
                traces={
                    "trace_a": {
                        "trace_id": "trace_a",
                        "title": "",
                        "rank": 1,
                        "distance_to_centroid": 0.1,
                        "x": 1.1,
                        "y": 2.1,
                    },
                    "trace_b": {
                        "trace_id": "trace_b",
                        "title": "",
                        "rank": 2,
                        "distance_to_centroid": 0.2,
                        "x": 0.9,
                        "y": 1.9,
                    },
                    "trace_c": {
                        "trace_id": "trace_c",
                        "title": "",
                        "rank": 3,
                        "distance_to_centroid": 0.3,
                        "x": 1.2,
                        "y": 2.2,
                    },
                },
            ),
            1: ClusterTraceData(
                cluster_id=1,
                size=2,
                centroid_x=-1.0,
                centroid_y=-2.0,
                traces={
                    "trace_d": {
                        "trace_id": "trace_d",
                        "title": "",
                        "rank": 1,
                        "distance_to_centroid": 0.15,
                        "x": -1.1,
                        "y": -2.1,
                    },
                    "trace_e": {
                        "trace_id": "trace_e",
                        "title": "",
                        "rank": 2,
                        "distance_to_centroid": 0.25,
                        "x": -0.9,
                        "y": -1.9,
                    },
                },
            ),
        }

    if trace_summaries is None:
        trace_summaries = {
            "trace_a": {
                "title": "User login flow",
                "flow_diagram": "A -> B -> C",
                "bullets": "- Point 1",
                "interesting_notes": "Note 1",
            },
            "trace_b": {
                "title": "User signup flow",
                "flow_diagram": "X -> Y -> Z",
                "bullets": "- Point 2",
                "interesting_notes": "Note 2",
            },
            "trace_c": {
                "title": "Password reset",
                "flow_diagram": "P -> Q -> R",
                "bullets": "- Point 3",
                "interesting_notes": "Note 3",
            },
            "trace_d": {
                "title": "API error handling",
                "flow_diagram": "E1 -> E2",
                "bullets": "- Error point",
                "interesting_notes": "Error note",
            },
            "trace_e": {
                "title": "Timeout retry logic",
                "flow_diagram": "T1 -> T2",
                "bullets": "- Retry point",
                "interesting_notes": "Retry note",
            },
        }

    if current_labels is None:
        current_labels = {}

    return {
        "team_id": 1,
        "cluster_data": cluster_data,
        "all_trace_summaries": trace_summaries,
        "current_labels": current_labels,
        "messages": [],
    }


class TestGetClustersOverview:
    def test_returns_all_clusters_sorted_by_id(self):
        state = make_test_state()

        result = get_clusters_overview.invoke({"state": state})
        data = json.loads(result)

        assert len(data) == 2
        assert data[0]["cluster_id"] == 0
        assert data[1]["cluster_id"] == 1

    def test_includes_size_and_centroid(self):
        state = make_test_state()

        result = get_clusters_overview.invoke({"state": state})
        data = json.loads(result)

        assert data[0]["size"] == 3
        assert data[0]["centroid_x"] == 1.0
        assert data[0]["centroid_y"] == 2.0


class TestGetAllClustersWithSampleTitles:
    def test_returns_sample_titles_for_each_cluster(self):
        state = make_test_state()

        result = get_all_clusters_with_sample_titles.invoke({"state": state, "titles_per_cluster": 10})
        data = json.loads(result)

        assert len(data) == 2
        assert data[0]["cluster_id"] == 0
        assert len(data[0]["sample_titles"]) == 3
        assert "User login flow" in data[0]["sample_titles"]

    def test_respects_titles_per_cluster_limit(self):
        state = make_test_state()

        result = get_all_clusters_with_sample_titles.invoke({"state": state, "titles_per_cluster": 1})
        data = json.loads(result)

        assert len(data[0]["sample_titles"]) == 1

    def test_titles_sorted_by_rank(self):
        state = make_test_state()

        result = get_all_clusters_with_sample_titles.invoke({"state": state, "titles_per_cluster": 10})
        data = json.loads(result)

        cluster_0 = next(c for c in data if c["cluster_id"] == 0)
        assert cluster_0["sample_titles"][0] == "User login flow"


class TestGetClusterTraceTitles:
    def test_returns_traces_for_cluster(self):
        state = make_test_state()

        result = get_cluster_trace_titles.invoke({"state": state, "cluster_id": 0, "limit": 30})
        data = json.loads(result)

        assert len(data) == 3
        assert all("trace_id" in item for item in data)
        assert all("title" in item for item in data)

    def test_returns_empty_for_nonexistent_cluster(self):
        state = make_test_state()

        result = get_cluster_trace_titles.invoke({"state": state, "cluster_id": 999, "limit": 30})
        data = json.loads(result)

        assert data == []

    def test_respects_limit(self):
        state = make_test_state()

        result = get_cluster_trace_titles.invoke({"state": state, "cluster_id": 0, "limit": 2})
        data = json.loads(result)

        assert len(data) == 2

    def test_sorted_by_rank(self):
        state = make_test_state()

        result = get_cluster_trace_titles.invoke({"state": state, "cluster_id": 0, "limit": 30})
        data = json.loads(result)

        ranks = [item["rank"] for item in data]
        assert ranks == sorted(ranks)


class TestGetTraceDetails:
    def test_returns_full_details_for_traces(self):
        state = make_test_state()

        result = get_trace_details.invoke({"state": state, "trace_ids": ["trace_a", "trace_d"]})
        data = json.loads(result)

        assert len(data) == 2
        assert data[0]["trace_id"] == "trace_a"
        assert data[0]["title"] == "User login flow"
        assert data[0]["flow_diagram"] == "A -> B -> C"
        assert data[0]["bullets"] == "- Point 1"
        assert data[0]["interesting_notes"] == "Note 1"

    def test_skips_nonexistent_traces(self):
        state = make_test_state()

        result = get_trace_details.invoke({"state": state, "trace_ids": ["trace_a", "nonexistent"]})
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["trace_id"] == "trace_a"


class TestGetCurrentLabels:
    def test_returns_null_for_unlabeled_clusters(self):
        state = make_test_state()

        result = get_current_labels.invoke({"state": state})
        data = json.loads(result)

        assert data["0"] is None
        assert data["1"] is None

    def test_returns_labels_for_labeled_clusters(self):
        state = make_test_state(
            current_labels={
                0: ClusterLabel(title="Auth Flows", description="Authentication patterns"),
            }
        )

        result = get_current_labels.invoke({"state": state})
        data = json.loads(result)

        assert data["0"]["title"] == "Auth Flows"
        assert data["0"]["description"] == "Authentication patterns"
        assert data["1"] is None


class TestSetClusterLabel:
    def test_sets_label_in_state(self):
        state = make_test_state()

        result = set_cluster_label.invoke(
            {
                "state": state,
                "cluster_id": 0,
                "title": "User Authentication",
                "description": "Login and signup flows",
            }
        )

        assert "Label set for cluster 0" in result
        assert state["current_labels"][0].title == "User Authentication"
        assert state["current_labels"][0].description == "Login and signup flows"

    def test_overwrites_existing_label(self):
        state = make_test_state(current_labels={0: ClusterLabel(title="Old Title", description="Old desc")})

        set_cluster_label.invoke(
            {
                "state": state,
                "cluster_id": 0,
                "title": "New Title",
                "description": "New desc",
            }
        )

        assert state["current_labels"][0].title == "New Title"


class TestBulkSetLabels:
    def test_sets_multiple_labels(self):
        state = make_test_state()

        result = bulk_set_labels.invoke(
            {
                "state": state,
                "labels": [
                    {"cluster_id": 0, "title": "Cluster A", "description": "Desc A"},
                    {"cluster_id": 1, "title": "Cluster B", "description": "Desc B"},
                ],
            }
        )

        assert "Labels set for 2 clusters" in result
        assert state["current_labels"][0].title == "Cluster A"
        assert state["current_labels"][1].title == "Cluster B"


class TestFinalizeLabels:
    def test_returns_count_of_labeled_clusters(self):
        state = make_test_state(current_labels={0: ClusterLabel(title="A", description="A desc")})

        result = finalize_labels.invoke({"state": state})

        assert "1/2 clusters labeled" in result


class TestFillMissingLabels:
    def test_preserves_existing_labels(self):
        existing = {0: ClusterLabel(title="Existing", description="Existing desc")}
        cluster_data = {
            0: ClusterTraceData(cluster_id=0, size=5, centroid_x=0, centroid_y=0, traces={}),
            1: ClusterTraceData(cluster_id=1, size=3, centroid_x=1, centroid_y=1, traces={}),
        }

        result = _fill_missing_labels(existing, cluster_data)

        assert result[0].title == "Existing"

    def test_fills_default_for_missing_clusters(self):
        existing: dict = {}
        cluster_data = {
            0: ClusterTraceData(cluster_id=0, size=5, centroid_x=0, centroid_y=0, traces={}),
        }

        result = _fill_missing_labels(existing, cluster_data)

        assert result[0].title == "Cluster 0"
        assert "5 similar traces" in result[0].description

    def test_fills_outliers_label_for_noise_cluster(self):
        existing: dict = {}
        cluster_data = {
            -1: ClusterTraceData(cluster_id=-1, size=10, centroid_x=0, centroid_y=0, traces={}),
        }

        result = _fill_missing_labels(existing, cluster_data)

        assert result[-1].title == "Outliers"
        assert "edge cases" in result[-1].description.lower()


class TestRunLabelingAgentIntegration:
    @patch("posthog.temporal.llm_analytics.trace_clustering.labeling_agent.graph._get_llm")
    @patch("posthog.temporal.llm_analytics.trace_clustering.labeling_agent.graph.create_react_agent")
    def test_runs_agent_and_returns_labels(self, mock_create_agent, mock_get_llm):
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_agent.invoke.return_value = {
            "messages": [HumanMessage(content="done")],
            "current_labels": {
                0: ClusterLabel(title="Generated Label", description="Generated desc"),
            },
        }

        cluster_data = {
            0: ClusterTraceData(cluster_id=0, size=5, centroid_x=0, centroid_y=0, traces={}),
            1: ClusterTraceData(cluster_id=1, size=3, centroid_x=1, centroid_y=1, traces={}),
        }

        result = run_labeling_agent(
            team_id=1,
            cluster_data=cluster_data,
            all_trace_summaries={},
        )

        assert result[0].title == "Generated Label"
        assert result[1].title == "Cluster 1"
        mock_create_agent.assert_called_once()

    @patch("posthog.temporal.llm_analytics.trace_clustering.labeling_agent.graph._get_llm")
    @patch("posthog.temporal.llm_analytics.trace_clustering.labeling_agent.graph.create_react_agent")
    def test_handles_agent_error_gracefully(self, mock_create_agent, mock_get_llm):
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_agent.invoke.side_effect = Exception("LLM error")

        cluster_data = {
            0: ClusterTraceData(cluster_id=0, size=5, centroid_x=0, centroid_y=0, traces={}),
        }

        result = run_labeling_agent(
            team_id=1,
            cluster_data=cluster_data,
            all_trace_summaries={},
        )

        assert result[0].title == "Cluster 0"

    @patch("posthog.temporal.llm_analytics.trace_clustering.labeling_agent.graph._get_llm")
    @patch("posthog.temporal.llm_analytics.trace_clustering.labeling_agent.graph.create_react_agent")
    def test_passes_correct_config_to_agent(self, mock_create_agent, mock_get_llm):
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_agent.invoke.return_value = {"messages": [], "current_labels": {}}

        cluster_data = {
            0: ClusterTraceData(cluster_id=0, size=5, centroid_x=0, centroid_y=0, traces={}),
        }

        run_labeling_agent(
            team_id=1,
            cluster_data=cluster_data,
            all_trace_summaries={},
        )

        call_args = mock_agent.invoke.call_args
        config = call_args[0][1]
        assert "recursion_limit" in config
