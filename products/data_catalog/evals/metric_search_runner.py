"""Seed the invented catalog, run a search case for one variant, and score the ranked result.

The eval suite and the backend regression test share this module. Scoring is pure, so a test can
check it without a database.
"""

import time
from collections.abc import Callable, Sequence
from typing import Any

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope

from products.data_catalog.backend.logic.metric_embeddings import (
    METRIC_EMBEDDING_MODEL,
    metric_search_text,
    search_text_hash,
)
from products.data_catalog.backend.logic.metric_search import SEARCH_DEFAULT_LIMIT, SEMANTIC_TOP_K, search_metrics
from products.data_catalog.backend.models import Metric
from products.data_catalog.evals.metric_search_cases import FIXTURE_METRICS, CaseType, SearchCase

Embedder = Callable[[Sequence[str]], list[list[float]]]


@frozen
class SearchVariant:
    """One row of the plan's comparison: lexical search alone (A), or merged with semantic search (A + C)."""

    name: str
    semantic: bool
    semantic_top_k: int = SEMANTIC_TOP_K


LEXICAL = SearchVariant(name="lexical", semantic=False)
HYBRID = SearchVariant(name="hybrid", semantic=True)


def seed_metric_search_catalog(team_id: int, *, embed: Embedder | None = None) -> list[Metric]:
    """Write the fixture catalog into the team. With ``embed``, store a vector on every metric."""
    with team_scope(team_id):
        metrics = [
            Metric.objects.for_team(team_id).create(
                team_id=team_id,
                name=fixture.name,
                display_name=fixture.display_name,
                description=fixture.description,
                unit=fixture.unit,
                status=fixture.status,
                definition={"kind": "HogQLQuery", "query": fixture.hogql} if fixture.hogql else None,
            )
            for fixture in FIXTURE_METRICS
        ]
        if embed is not None:
            texts = [metric_search_text(metric) for metric in metrics]
            vectors = embed(texts)
            for metric, text, vector in zip(metrics, texts, vectors, strict=True):
                Metric.objects.for_team(team_id).filter(pk=metric.pk).update(
                    embedding=vector, embedding_model=METRIC_EMBEDDING_MODEL, embedding_text_hash=search_text_hash(text)
                )
    return metrics


def run_case(
    team_id: int, case: SearchCase, variant: SearchVariant, *, embed: Embedder | None = None
) -> dict[str, Any]:
    """Search the seeded team the way the variant says. The dict is the scorer output."""
    if variant.semantic and embed is None:
        raise ValueError(f"Variant {variant.name} needs an embedder")

    def embed_query(text: str) -> list[float] | None:
        return embed([text])[0] if embed is not None else None

    started = time.perf_counter()
    with team_scope(team_id):
        result = search_metrics(
            Metric.objects.for_team(team_id).filter(deleted=False),
            case.queries,
            limit=SEARCH_DEFAULT_LIMIT,
            embed_query=embed_query if variant.semantic else None,
            semantic_top_k=variant.semantic_top_k,
        )
    latency_ms = (time.perf_counter() - started) * 1000
    return {
        "variant": variant.name,
        "case_type": case.case_type.value,
        "ranked": [hit.metric.name for hit in result.hits],
        "match_reasons": [hit.match_reason for hit in result.hits],
        "confident_match": result.confident_match,
        "search_mode": result.search_mode,
        "latency_ms": round(latency_ms, 1),
    }


def _rank(ranked: Sequence[str], name: str | None) -> int | None:
    if name is None or name not in ranked:
        return None
    return ranked.index(name)


def score_case(case: SearchCase, ranked: Sequence[str], confident_match: bool) -> dict[str, float | None]:
    """Scores for one case. None means the score does not apply to this case type."""
    if case.case_type == CaseType.REAL_GAP:
        return {
            "recall": None,
            "correct_no_match": 0.0 if confident_match else 1.0,
            "sibling_ranked_above": None,
            "confident_when_present": None,
        }
    found_ranks = [rank for name in case.expected if (rank := _rank(ranked, name)) is not None]
    sibling_score: float | None = None
    if case.case_type == CaseType.NEAR_SIBLING:
        sibling_rank = _rank(ranked, case.ranked_above)
        best = min(found_ranks) if found_ranks else None
        sibling_score = 1.0 if best is not None and (sibling_rank is None or best < sibling_rank) else 0.0
    return {
        "recall": 1.0 if found_ranks else 0.0,
        "correct_no_match": None,
        "sibling_ranked_above": sibling_score,
        "confident_when_present": 1.0 if confident_match else 0.0,
    }


def openai_embedder(model: str = "text-embedding-3-small") -> Embedder:
    """The model behind the embedding worker's text-embedding-3-small-1536, called directly.

    The eval calls OpenAI itself, so it runs without the embedding worker and without org AI consent.
    """

    def embed(texts: Sequence[str]) -> list[list[float]]:
        # Built on first use, so listing or enrolling the suite needs no OpenAI key.
        from openai import OpenAI  # noqa: PLC0415 — keeps the OpenAI client off the import path of lexical runs

        # Bounded below the harness's case deadline, so a stalled call ends instead of holding a thread.
        response = OpenAI(timeout=30.0, max_retries=2).embeddings.create(model=model, input=list(texts))
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]

    return embed
