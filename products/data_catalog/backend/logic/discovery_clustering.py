"""Semantic clustering of discovered metric candidates.

Structural fingerprinting (``discovery.distill_sql``) groups literal variants of one query, but
two queries computing the same business concept differently — MRR via ``sumIf`` and MRR via a
subquery, or a dashboard insight next to the ad-hoc SQL that recomputes it — land as separate
candidates. This module embeds each candidate's distinguishing text (title, human-written
description, dashboards, SQL) and merges near-duplicates with agglomerative clustering over cosine
distance, so the review queue shows one canonical candidate per concept with its semantic
duplicates attached as evidence.

Clustering is an enhancement, never a gate: any embedding failure returns the report unchanged.
The merge math is pure (candidates + a pairwise distance matrix in, merged candidates out), so it
tests and runs offline without an embedding service.
"""

import dataclasses
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Optional

import numpy as np
import structlog
from sklearn.cluster import AgglomerativeClustering

from posthog.api.embedding_worker import generate_embedding
from posthog.dataclasses import frozen
from posthog.models import Team

from .discovery import DiscoveryReport, MetricCandidate

logger = structlog.get_logger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small-1536"
# Cosine distance below which two candidates count as one concept. Merging two genuinely
# different metrics is worse than showing a near-duplicate twice, so the threshold errs toward
# not merging: measured on real candidates, restatements of one query land under ~0.09 while
# distinct-but-related metrics over the same tables start around 0.13.
DEFAULT_DISTANCE_THRESHOLD = 0.1
# Names and the SQL head carry most of the meaning; the SQL tail mostly repeats table and column
# tokens, so a bounded slice keeps embedding cost flat without losing the signal.
MAX_EMBED_SQL_CHARS = 1200
EMBED_TIMEOUT_SECONDS = 30.0

# Auto-generated description prefixes (see discovery._insight_metric_candidates and
# discovery._sql_metric_candidates). Templated prose is near-identical across candidates, which
# compresses embedding distances between distinct metrics — so it stays out of embedding texts.
_TEMPLATED_DESCRIPTION_PREFIXES = ("Proposed from the saved insight", "Recurring SQL query computing")


@frozen
class CandidateCluster:
    """One merged group: the surviving candidate and the near-duplicates folded into it."""

    canonical_name: str
    merged_names: tuple[str, ...]


def candidate_embedding_text(candidate: MetricCandidate) -> str:
    """The text that stands in for a candidate in embedding space.

    Only distinguishing facts go in: the title, a human-written description, the dashboards, and
    the SQL itself. Auto-generated descriptions are skipped — they repeat one template across
    candidates and would pull distinct metrics together.
    """
    parts = [f"Metric: {candidate.display_name or candidate.name}"]
    if candidate.description and not candidate.description.startswith(_TEMPLATED_DESCRIPTION_PREFIXES):
        parts.append(f"Description: {candidate.description}")
    dashboards = candidate.evidence.get("dashboards")
    if dashboards:
        parts.append("Dashboards: " + ", ".join(str(d) for d in dashboards))
    definition = candidate.definition or {}
    sql = definition.get("query") if isinstance(definition, dict) else None
    if isinstance(sql, str) and sql.strip():
        parts.append(f"SQL: {sql.strip()[:MAX_EMBED_SQL_CHARS]}")
    return "\n".join(parts)


def pairwise_cosine_distances(embeddings: Sequence[Sequence[float]]) -> np.ndarray:
    matrix = np.asarray(embeddings, dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normalized = matrix / np.clip(norms, a_min=1e-12, a_max=None)
    distances = 1.0 - normalized @ normalized.T
    return np.clip(distances, a_min=0.0, a_max=2.0)


def merge_semantic_duplicates(
    candidates: Sequence[MetricCandidate],
    distances: np.ndarray,
    *,
    distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
) -> tuple[list[MetricCandidate], list[CandidateCluster]]:
    """Merge candidates whose pairwise distance clusters them together.

    Only SQL-derived candidates are ever merged away: each insight-linked candidate points at a
    distinct saved insight someone deliberately curated (with its own drift tracking), so all of
    them survive — dashboards routinely carry sibling charts ("New revenue" next to "Expanded
    revenue") that embed close together yet mean different things. Within a cluster the
    highest-confidence survivor is canonical, and the folded-in duplicates are recorded on it as
    ``semantic_duplicates`` evidence rather than silently dropped, so a reviewer still sees them.
    """
    if len(candidates) < 2:
        return list(candidates), []
    if distances.shape != (len(candidates), len(candidates)):
        raise ValueError(f"Distance matrix shape {distances.shape} does not match {len(candidates)} candidates.")

    clusterer = AgglomerativeClustering(
        metric="precomputed",
        linkage="average",
        distance_threshold=distance_threshold,
        n_clusters=None,
    )
    labels = clusterer.fit_predict(distances)

    members_by_label: dict[int, list[MetricCandidate]] = defaultdict(list)
    for candidate, label in zip(candidates, labels):
        members_by_label[int(label)].append(candidate)

    merged: list[MetricCandidate] = []
    clusters: list[CandidateCluster] = []
    for members in members_by_label.values():
        members.sort(
            key=lambda c: (bool(c.source_insight_short_id), c.confidence, c.evidence.get("run_count", 0)), reverse=True
        )
        insight_linked = [m for m in members if m.source_insight_short_id]
        duplicates = [m for m in members if not m.source_insight_short_id]
        if insight_linked:
            canonical = insight_linked[0]
            merged.extend(insight_linked[1:])
        else:
            canonical, *duplicates = duplicates
        if not duplicates:
            merged.append(canonical)
            continue
        duplicate_names = tuple(d.name for d in duplicates)
        merged.append(
            dataclasses.replace(
                canonical,
                reasoning=(
                    canonical.reasoning
                    + f" {len(duplicates)} semantically similar candidate(s) were merged into this one: "
                    + ", ".join(duplicate_names)
                    + "."
                ),
                evidence={
                    **canonical.evidence,
                    "semantic_duplicates": [
                        {
                            "name": d.name,
                            "signal": d.evidence.get("signal"),
                            "run_count": d.evidence.get("run_count"),
                            "insight_short_id": d.source_insight_short_id,
                        }
                        for d in duplicates
                    ],
                },
            )
        )
        clusters.append(CandidateCluster(canonical_name=canonical.name, merged_names=duplicate_names))

    merged.sort(key=lambda c: c.confidence, reverse=True)
    return merged, clusters


def team_embedder(team: Team, *, model: str = EMBEDDING_MODEL) -> Callable[[list[str]], Optional[list[list[float]]]]:
    """An embed function backed by the embedding worker. Returns None on any failure (fail-soft)."""

    def embed(texts: list[str]) -> Optional[list[list[float]]]:
        try:
            return [
                generate_embedding(team, text, model=model, timeout=EMBED_TIMEOUT_SECONDS).embedding for text in texts
            ]
        except Exception:
            logger.exception("discovery: embedding failed, skipping semantic clustering", team_id=team.id)
            return None

    return embed


def apply_semantic_clustering(
    report: DiscoveryReport,
    *,
    embed_texts: Callable[[list[str]], Optional[list[list[float]]]],
    distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
) -> DiscoveryReport:
    """Return the report with near-duplicate metric candidates merged, or unchanged on failure."""
    candidates = list(report.metric_candidates)
    if len(candidates) < 2:
        return report

    embeddings = embed_texts([candidate_embedding_text(c) for c in candidates])
    if embeddings is None or len(embeddings) != len(candidates):
        return dataclasses.replace(report, stats={**report.stats, "semantic_clustering": "skipped"})

    merged, clusters = merge_semantic_duplicates(
        candidates, pairwise_cosine_distances(embeddings), distance_threshold=distance_threshold
    )
    return dataclasses.replace(
        report,
        metric_candidates=tuple(merged),
        stats={
            **report.stats,
            "semantic_clustering": {
                "distance_threshold": distance_threshold,
                "clusters_merged": len(clusters),
                "candidates_merged_away": sum(len(c.merged_names) for c in clusters),
            },
        },
    )
