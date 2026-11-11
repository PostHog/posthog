"""Embeddings for semantic metric search.

The vector lives on the metric row. A metric write schedules a refresh after commit, and the refresh
calls the shared embedding worker only when the search text changed. The backfill command runs the
same refresh over metrics that exist already.

Embedding sends metric text to an outside model provider, so it runs only for organizations that
approved AI data processing. The read path also needs the semantic search feature flag.
"""

import hashlib
from collections.abc import Iterable

import structlog
import posthoganalytics

from posthog.api.embedding_worker import generate_embedding
from posthog.dataclasses import frozen
from posthog.models import Team

from ..models import Metric

logger = structlog.get_logger(__name__)

METRIC_EMBEDDING_MODEL = "text-embedding-3-small-1536"
SEMANTIC_SEARCH_FEATURE_FLAG = "data-catalog-metric-semantic-search"

# A query embedding sits in the request path, so a slow worker must fall back to lexical search fast.
QUERY_EMBEDDING_TIMEOUT_SECONDS = 2.0
DOCUMENT_EMBEDDING_TIMEOUT_SECONDS = 15.0

# A write to any of these fields changes the search text, so it needs a fresh embedding.
EMBEDDED_FIELDS = frozenset({"name", "display_name", "description", "unit"})


@frozen
class EmbeddingRefresh:
    metric_id: str
    refreshed: bool
    reason: str


def metric_search_text(metric: Metric) -> str:
    """Readable words that describe the metric. The query definition stays out: it is code, not meaning."""
    spelled_name = metric.name.replace("_", " ")
    lines = [metric.display_name or spelled_name]
    if metric.display_name and metric.display_name.lower() != spelled_name.lower():
        lines.append(spelled_name)
    lines.append(metric.description)
    if metric.unit:
        lines.append(f"Unit: {metric.unit}")
    return "\n".join(line for line in lines if line)


def search_text_hash(text: str) -> str:
    return hashlib.sha256(f"{METRIC_EMBEDDING_MODEL}\n{text}".encode()).hexdigest()


def embedding_is_current(metric: Metric) -> bool:
    return (
        metric.embedding is not None
        and metric.embedding_model == METRIC_EMBEDDING_MODEL
        and metric.embedding_text_hash == search_text_hash(metric_search_text(metric))
    )


def can_embed(team: Team) -> bool:
    return bool(team.organization.is_ai_data_processing_approved)


def semantic_search_enabled(team: Team) -> bool:
    """True when the read path may embed a query: AI data processing approved and the flag on."""
    if not can_embed(team):
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SEMANTIC_SEARCH_FEATURE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={"organization": {"id": str(team.organization_id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("metric_semantic_search_flag_check_failed", team_id=team.id)
        return False


def embed_search_query(team: Team, query: str) -> list[float] | None:
    """Embed a search query, or return None so the search falls back to the lexical lane."""
    try:
        return generate_embedding(
            team, query, model=METRIC_EMBEDDING_MODEL, timeout=QUERY_EMBEDDING_TIMEOUT_SECONDS
        ).embedding
    except Exception:
        logger.warning("metric_search_query_embedding_failed", team_id=team.id, exc_info=True)
        return None


def refresh_metric_embedding(metric: Metric, *, force: bool = False) -> EmbeddingRefresh:
    """Embed the metric's search text when it changed, and store the vector without a model save.

    The store is one conditional update on the embedded fields. When a write changed the text while the
    worker answered, no row matches and the vector is dropped, because that write scheduled its own refresh.
    """
    metric_id = str(metric.id)
    if metric.deleted:
        return EmbeddingRefresh(metric_id=metric_id, refreshed=False, reason="deleted")
    if not can_embed(metric.team):
        return EmbeddingRefresh(metric_id=metric_id, refreshed=False, reason="ai_data_processing_not_approved")
    if not force and embedding_is_current(metric):
        return EmbeddingRefresh(metric_id=metric_id, refreshed=False, reason="current")

    text = metric_search_text(metric)
    text_hash = search_text_hash(text)
    response = generate_embedding(
        metric.team, text, model=METRIC_EMBEDDING_MODEL, timeout=DOCUMENT_EMBEDDING_TIMEOUT_SECONDS
    )
    updated = (
        Metric.objects.for_team(metric.team_id)
        .filter(
            pk=metric.pk,
            deleted=False,
            name=metric.name,
            display_name=metric.display_name,
            description=metric.description,
            unit=metric.unit,
        )
        .update(embedding=response.embedding, embedding_model=METRIC_EMBEDDING_MODEL, embedding_text_hash=text_hash)
    )
    if not updated:
        return EmbeddingRefresh(metric_id=metric_id, refreshed=False, reason="changed")
    return EmbeddingRefresh(metric_id=metric_id, refreshed=True, reason="refreshed")


def metrics_needing_embedding(metrics: Iterable[Metric]) -> list[Metric]:
    return [metric for metric in metrics if not embedding_is_current(metric)]
