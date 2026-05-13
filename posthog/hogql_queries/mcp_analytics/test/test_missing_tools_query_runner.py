import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from posthog.models.event.util import create_event
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.hogql_queries.mcp_analytics.missing_tools_query_runner import (
    MissingToolsCandidatesParams,
    MissingToolsCandidatesRunner,
)


def _emit_intent_clusters_event(team, clusters_payload: dict[str, Any]) -> None:
    create_event(
        event_uuid=uuid.uuid4(),
        event="$mcp_intent_clusters",
        team=team,
        distinct_id=f"mcp_analytics_clustering_{team.id}",
        properties=clusters_payload,
        timestamp=datetime.now(UTC),
    )


class TestMissingToolsQueryRunner(ClickhouseTestMixin, BaseTest):
    def test_returns_empty_when_no_clusters_event(self) -> None:
        runner = MissingToolsCandidatesRunner(
            team=self.team,
            params=MissingToolsCandidatesParams(probe_phrases=[]),
        )
        result = runner.run()
        assert result.clustering_run_id == ""
        assert result.intent_clusters == []
        assert result.llm_stated_gaps == []

    def test_returns_intent_clusters_from_latest_event(self) -> None:
        _emit_intent_clusters_event(
            self.team,
            {
                "$mcp_clustering_run_id": "run-1",
                "$mcp_window_start": "2026-05-01T00:00:00Z",
                "$mcp_window_end": "2026-05-08T00:00:00Z",
                "$mcp_total_intents_analyzed": 42,
                "$mcp_clusters": [
                    {
                        "cluster_id": 0,
                        "title": "Edit dashboard",
                        "description": "Users want to edit dashboards directly",
                        "gap_score": 0.8,
                        "size": 5,
                        "aggregate_error_rate": 0.5,
                        "aggregate_empty_rate": 0.2,
                        "avg_distinct_tools_attempted": 3.4,
                        "members": [
                            {
                                "intent": "edit dashboard layout",
                                "stat": {
                                    "intent": "edit dashboard layout",
                                    "total_calls": 10,
                                    "error_count": 5,
                                    "empty_response_count": 2,
                                    "distinct_tools_attempted": 4,
                                    "dominant_tool": "dashboard_get",
                                    "sample_session_ids": [],
                                },
                                "distance_to_centroid": 0.1,
                            }
                        ],
                    },
                    {
                        "cluster_id": 1,
                        "title": "Resolve flag",
                        "description": "",
                        "gap_score": 0.3,
                        "size": 2,
                        "aggregate_error_rate": 0.1,
                        "aggregate_empty_rate": 0.0,
                        "avg_distinct_tools_attempted": 1.5,
                        "members": [],
                    },
                ],
            },
        )

        runner = MissingToolsCandidatesRunner(
            team=self.team,
            params=MissingToolsCandidatesParams(probe_phrases=[]),
        )
        result = runner.run()

        assert result.clustering_run_id == "run-1"
        assert result.window_start == "2026-05-01T00:00:00Z"
        assert result.window_end == "2026-05-08T00:00:00Z"
        assert len(result.intent_clusters) == 2
        # Insertion order is preserved — the runner doesn't re-sort (the writer already
        # sorted by gap_score before emit).
        assert result.intent_clusters[0].title == "Edit dashboard"
        assert result.intent_clusters[0].gap_score == 0.8
        assert result.intent_clusters[0].sample_intents[0].intent == "edit dashboard layout"
        assert result.intent_clusters[0].sample_intents[0].error_rate == 0.5
        assert result.intent_clusters[0].sample_intents[0].empty_rate == 0.2
        assert result.intent_clusters[1].title == "Resolve flag"

    def test_reads_latest_event_when_multiple_exist(self) -> None:
        _emit_intent_clusters_event(
            self.team,
            {
                "$mcp_clustering_run_id": "older-run",
                "$mcp_window_start": "2026-04-01T00:00:00Z",
                "$mcp_window_end": "2026-04-08T00:00:00Z",
                "$mcp_total_intents_analyzed": 10,
                "$mcp_clusters": [],
            },
        )
        _emit_intent_clusters_event(
            self.team,
            {
                "$mcp_clustering_run_id": "newer-run",
                "$mcp_window_start": "2026-05-01T00:00:00Z",
                "$mcp_window_end": "2026-05-08T00:00:00Z",
                "$mcp_total_intents_analyzed": 12,
                "$mcp_clusters": [],
            },
        )

        runner = MissingToolsCandidatesRunner(
            team=self.team,
            params=MissingToolsCandidatesParams(probe_phrases=[]),
        )
        result = runner.run()
        assert result.clustering_run_id == "newer-run"

    def test_search_llm_stated_gaps_is_called_per_probe(self) -> None:
        # We don't have a real embedding worker in tests, so we patch _search_one_probe
        # and verify the merge / dedupe logic still works.
        from posthog.hogql_queries.mcp_analytics.missing_tools_query_runner import LLMStatedGapDTO

        gaps_by_probe = {
            "probe-a": [
                LLMStatedGapDTO(
                    probe_phrase="probe-a", matched_text="alpha", distance=0.1, document_id="doc-1"
                ),
                LLMStatedGapDTO(
                    probe_phrase="probe-a", matched_text="beta", distance=0.3, document_id="doc-2"
                ),
            ],
            "probe-b": [
                # Same document seen via a different probe at a closer distance — should win.
                LLMStatedGapDTO(
                    probe_phrase="probe-b", matched_text="alpha-v2", distance=0.05, document_id="doc-1"
                ),
                LLMStatedGapDTO(
                    probe_phrase="probe-b", matched_text="gamma", distance=0.4, document_id="doc-3"
                ),
            ],
        }

        with patch.object(
            MissingToolsCandidatesRunner,
            "_search_one_probe",
            side_effect=lambda probe: gaps_by_probe.get(probe, []),
        ):
            runner = MissingToolsCandidatesRunner(
                team=self.team,
                params=MissingToolsCandidatesParams(probe_phrases=["probe-a", "probe-b"]),
            )
            result = runner.run()

        document_ids = [g.document_id for g in result.llm_stated_gaps]
        assert sorted(document_ids) == ["doc-1", "doc-2", "doc-3"]
        # doc-1 should appear with the closer (probe-b) match
        doc1 = next(g for g in result.llm_stated_gaps if g.document_id == "doc-1")
        assert doc1.distance == 0.05
        assert doc1.probe_phrase == "probe-b"
        assert doc1.matched_text == "alpha-v2"
        # Results are sorted by distance ascending
        distances = [g.distance for g in result.llm_stated_gaps]
        assert distances == sorted(distances)
