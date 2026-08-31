import dataclasses

from django.test import SimpleTestCase

import numpy as np

from products.data_catalog.backend.logic.discovery import DiscoveryReport, MetricCandidate
from products.data_catalog.backend.logic.discovery_clustering import (
    apply_semantic_clustering,
    candidate_embedding_text,
    merge_semantic_duplicates,
    pairwise_cosine_distances,
)


def _candidate(name: str, confidence: float, run_count: int = 0, sql: str | None = None) -> MetricCandidate:
    return MetricCandidate(
        name=name,
        display_name=name.replace("_", " "),
        description=f"Description of {name}.",
        definition={"kind": "HogQLQuery", "query": sql} if sql else None,
        source_insight_short_id=None if sql else f"short_{name}",
        unit="",
        confidence=confidence,
        reasoning=f"Reasoning for {name}.",
        evidence={"signal": "query_history" if sql else "insight", "run_count": run_count},
    )


def _report(candidates: list[MetricCandidate]) -> DiscoveryReport:
    return DiscoveryReport(
        metric_candidates=tuple(candidates), relationship_candidates=(), sql_groups=(), stats={"window_days": 30}
    )


# Unit vectors in embedding space: a and a_dup are nearly parallel (one concept expressed twice),
# b is orthogonal to both (a different concept).
_NEAR = [1.0, 0.0, 0.05]
_NEAR_DUP = [1.0, 0.05, 0.0]
_FAR = [0.0, 1.0, 0.0]


class TestMergeSemanticDuplicates(SimpleTestCase):
    def test_near_duplicates_merge_into_highest_confidence_candidate(self) -> None:
        candidates = [
            _candidate("mrr_monthly", confidence=0.8, run_count=96, sql="SELECT sum(mrr) FROM invoices"),
            _candidate(
                "monthly_sum_invoices", confidence=0.7, run_count=51, sql="SELECT sum(mrr) FROM invoices LIMIT 1"
            ),
            _candidate("weekly_signups", confidence=0.75, sql="SELECT count() FROM events"),
        ]
        distances = pairwise_cosine_distances([_NEAR, _NEAR_DUP, _FAR])
        merged, clusters = merge_semantic_duplicates(candidates, distances)

        assert sorted(c.name for c in merged) == ["mrr_monthly", "weekly_signups"]
        assert len(clusters) == 1
        assert clusters[0].canonical_name == "mrr_monthly"
        assert clusters[0].merged_names == ("monthly_sum_invoices",)

        canonical = next(c for c in merged if c.name == "mrr_monthly")
        assert canonical.definition == {"kind": "HogQLQuery", "query": "SELECT sum(mrr) FROM invoices"}
        assert canonical.evidence["semantic_duplicates"] == [
            {"name": "monthly_sum_invoices", "signal": "query_history", "run_count": 51, "insight_short_id": None}
        ]
        assert "monthly_sum_invoices" in canonical.reasoning

    def test_distant_candidates_stay_separate(self) -> None:
        candidates = [_candidate("a", 0.8), _candidate("b", 0.7)]
        merged, clusters = merge_semantic_duplicates(candidates, pairwise_cosine_distances([_NEAR, _FAR]))
        assert len(merged) == 2
        assert clusters == []

    def test_insight_linked_candidates_never_merge_with_each_other(self) -> None:
        # Sibling dashboard charts ("New revenue" next to "Expanded revenue") embed close together
        # but each links to its own curated insight, so both must survive.
        candidates = [_candidate("new_revenue", 0.8), _candidate("expanded_revenue", 0.76)]
        merged, clusters = merge_semantic_duplicates(candidates, pairwise_cosine_distances([_NEAR, _NEAR_DUP]))
        assert sorted(c.name for c in merged) == ["expanded_revenue", "new_revenue"]
        assert clusters == []

    def test_sql_duplicate_folds_into_insight_linked_canonical(self) -> None:
        candidates = [
            _candidate("mrr_chart", 0.7),
            _candidate("mrr_sql", 0.8, run_count=96, sql="SELECT sum(mrr) FROM invoices"),
        ]
        merged, clusters = merge_semantic_duplicates(candidates, pairwise_cosine_distances([_NEAR, _NEAR_DUP]))
        assert [c.name for c in merged] == ["mrr_chart"]
        assert clusters[0].canonical_name == "mrr_chart"
        assert clusters[0].merged_names == ("mrr_sql",)
        assert merged[0].source_insight_short_id == "short_mrr_chart"

    def test_single_candidate_passes_through(self) -> None:
        candidates = [_candidate("only", 0.8)]
        merged, clusters = merge_semantic_duplicates(candidates, np.zeros((1, 1)))
        assert merged == candidates
        assert clusters == []


class TestApplySemanticClustering(SimpleTestCase):
    def test_merges_and_records_stats(self) -> None:
        report = _report(
            [
                _candidate("a", 0.8, sql="SELECT sum(x) FROM t"),
                _candidate("a_dup", 0.7, sql="SELECT sum(x) FROM t LIMIT 1"),
                _candidate("b", 0.75, sql="SELECT count() FROM u"),
            ]
        )
        clustered = apply_semantic_clustering(report, embed_texts=lambda texts: [_NEAR, _NEAR_DUP, _FAR])
        assert sorted(c.name for c in clustered.metric_candidates) == ["a", "b"]
        assert clustered.stats["semantic_clustering"] == {
            "distance_threshold": 0.1,
            "clusters_merged": 1,
            "candidates_merged_away": 1,
        }
        assert clustered.relationship_candidates == report.relationship_candidates

    def test_embedding_failure_leaves_report_unchanged(self) -> None:
        report = _report([_candidate("a", 0.8), _candidate("b", 0.7)])
        clustered = apply_semantic_clustering(report, embed_texts=lambda texts: None)
        assert clustered.metric_candidates == report.metric_candidates
        assert clustered.stats["semantic_clustering"] == "skipped"

    def test_embedding_count_mismatch_leaves_report_unchanged(self) -> None:
        report = _report([_candidate("a", 0.8), _candidate("b", 0.7)])
        clustered = apply_semantic_clustering(report, embed_texts=lambda texts: [_NEAR])
        assert clustered.metric_candidates == report.metric_candidates
        assert clustered.stats["semantic_clustering"] == "skipped"

    def test_embedding_text_carries_name_description_and_sql(self) -> None:
        candidate = _candidate("mrr_monthly", 0.8, sql="SELECT sum(mrr) FROM invoices")
        text = candidate_embedding_text(candidate)
        assert "mrr monthly" in text
        assert "Description of mrr_monthly." in text
        assert "SELECT sum(mrr) FROM invoices" in text

    def test_embedding_text_skips_templated_prose_and_carries_dashboards(self) -> None:
        # Auto-generated descriptions repeat one template across candidates and would compress
        # distances between distinct metrics.
        candidate = dataclasses.replace(
            _candidate("churn_rate", 0.8),
            description='Proposed from the saved insight "Churn rate" on the dashboard(s) "Churn analysis".',
            evidence={"signal": "insight", "run_count": 0, "dashboards": ["Churn analysis"]},
        )
        text = candidate_embedding_text(candidate)
        assert "Proposed from the saved insight" not in text
        assert "Dashboards: Churn analysis" in text
