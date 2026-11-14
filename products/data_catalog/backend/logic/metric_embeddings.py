"""Embeddings for semantic metric search.

The vector lives on the metric row. A metric write that changes the search text clears the vector and
schedules a refresh after commit, with no feature flag. The backfill sweep and the backfill command run the
same refresh over metrics with no vector, for teams with the backfill flag on. The sweep also repairs a
refresh that failed.

Embedding sends metric text to an outside model provider, so it runs only for organizations that
approved AI data processing. The read path also needs the semantic search feature flag.
"""

import hashlib
from collections.abc import Iterable
from enum import StrEnum

from django.db.models import Q

import structlog
import posthoganalytics

from posthog.api.embedding_worker import generate_embedding
from posthog.dataclasses import frozen
from posthog.models import Team

from ..models import Metric

logger = structlog.get_logger(__name__)

METRIC_EMBEDDING_MODEL = "text-embedding-3-small-1536"
SEMANTIC_SEARCH_FEATURE_FLAG = "data-catalog-metric-semantic-search"
EMBEDDING_BACKFILL_FEATURE_FLAG = "data-catalog-metric-embedding-backfill"

# A query embedding sits in the request path, so a slow worker must fall back to lexical search fast.
QUERY_EMBEDDING_TIMEOUT_SECONDS = 2.0
DOCUMENT_EMBEDDING_TIMEOUT_SECONDS = 15.0

# The backfill sweep queues at most this many refreshes per run, spaced this far apart, so one batch
# ends before the next run and the embedding worker sees a steady trickle.
BACKFILL_BATCH_SIZE = 100
BACKFILL_SPACING_SECONDS = 4
# Each team costs one flag call, so a run checks at most this many teams.
BACKFILL_TEAMS_PER_RUN = 200

# A write to any of these fields changes the search text, so it needs a fresh embedding.
EMBEDDED_FIELDS = frozenset({"name", "display_name", "description", "unit"})


class RefreshOutcome(StrEnum):
    REFRESHED = "refreshed"
    CURRENT = "current"
    CHANGED = "changed"
    DELETED = "deleted"
    AI_DATA_PROCESSING_NOT_APPROVED = "ai_data_processing_not_approved"


@frozen
class EmbeddingRefresh:
    metric_id: str
    outcome: RefreshOutcome

    @property
    def refreshed(self) -> bool:
        return self.outcome == RefreshOutcome.REFRESHED


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


def _flag_enabled(team: Team, flag: str) -> bool:
    if not can_embed(team):
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={"organization": {"id": str(team.organization_id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("metric_embedding_flag_check_failed", team_id=team.id, flag=flag)
        return False


def semantic_search_enabled(team: Team) -> bool:
    """True when the read path may embed a query: AI data processing approved and the flag on."""
    return _flag_enabled(team, SEMANTIC_SEARCH_FEATURE_FLAG)


def embedding_backfill_enabled(team: Team) -> bool:
    """True when the batch backfill may embed the team's existing metrics: AI data processing approved and the flag on."""
    return _flag_enabled(team, EMBEDDING_BACKFILL_FEATURE_FLAG)


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
        return EmbeddingRefresh(metric_id=metric_id, outcome=RefreshOutcome.DELETED)
    if not can_embed(metric.team):
        return EmbeddingRefresh(metric_id=metric_id, outcome=RefreshOutcome.AI_DATA_PROCESSING_NOT_APPROVED)
    if not force and embedding_is_current(metric):
        return EmbeddingRefresh(metric_id=metric_id, outcome=RefreshOutcome.CURRENT)

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
    outcome = RefreshOutcome.REFRESHED if updated else RefreshOutcome.CHANGED
    return EmbeddingRefresh(metric_id=metric_id, outcome=outcome)


def clear_stale_embedding(metric: Metric) -> None:
    """Drop the vector of a metric whose search text changed, so the backfill sweep finds it if the refresh fails.

    A write that resends the same text keeps its vector, because the stored hash still matches.
    """
    (
        Metric.objects.for_team(metric.team_id)
        .filter(pk=metric.pk, embedding__isnull=False)
        .exclude(embedding_text_hash=search_text_hash(metric_search_text(metric)))
        .update(embedding=None, embedding_text_hash="")
    )


def metrics_needing_embedding(metrics: Iterable[Metric]) -> list[Metric]:
    return [metric for metric in metrics if not embedding_is_current(metric)]


def metrics_to_backfill(limit: int) -> list[tuple[str, int]]:
    """``(metric id, team id)`` of live metrics with no vector from the current model, in teams with the
    backfill flag on. A text change clears the vector, so this also finds failed refreshes.
    Teams and metrics come in random order, so a metric that keeps failing cannot hold a batch.
    """
    missing = (
        Metric.objects.unscoped()
        .filter(deleted=False)
        .filter(Q(embedding__isnull=True) | ~Q(embedding_model=METRIC_EMBEDDING_MODEL))
    )
    teams = (
        Team.objects.filter(pk__in=missing.values("team_id"), organization__is_ai_data_processing_approved=True)
        .select_related("organization")
        .order_by("?")[:BACKFILL_TEAMS_PER_RUN]
    )
    picked: list[tuple[str, int]] = []
    for team in teams:
        if len(picked) >= limit:
            break
        if not embedding_backfill_enabled(team):
            continue
        metric_ids = missing.filter(team_id=team.id).order_by("?").values_list("id", flat=True)[: limit - len(picked)]
        picked.extend((str(metric_id), team.id) for metric_id in metric_ids)
    return picked
