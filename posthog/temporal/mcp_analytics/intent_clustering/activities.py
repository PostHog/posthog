"""Temporal activities for the MCP analytics intent clustering pipeline.

There is exactly one activity in v1: ``compute_intent_clusters_activity``.
It wraps the same orchestration the Celery task performs today, but with
Temporal-native heartbeats, retries, and replay determinism.

Why a single activity (and not 4 like trace_clustering):

1. **Payload limits.** A 500-intent corpus has embeddings of ~3 MB
   (500 × 1536 × 4 bytes). Temporal's hard payload limit is ~2 MiB; even
   compact serialisation would clip us. Keeping embeddings within one
   activity sidesteps the boundary entirely.
2. **Total runtime is small.** The full pipeline runs in ~30-60s with a warm
   cache. Trace_clustering split because labeling alone is 600s — that
   reasoning doesn't apply here.
3. **No expensive recompute on retry.** Embeddings are cached (PR #3) and
   ClickHouse fetches are idempotent. A retry costs O(seconds) of cache
   lookups, not O(minutes) of work.

If clustering grows (HDBSCAN/UMAP at higher cardinality, LLM labelling),
the activity boundary can be split later. Today it's single-activity.
"""

import asyncio

from django.db import transaction
from django.utils import timezone

import structlog
from temporalio import activity

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.mcp_analytics.intent_clustering.metrics import record_clusters_generated, record_intents_analyzed
from posthog.temporal.mcp_analytics.intent_clustering.models import (
    IntentClusteringResult,
    IntentClusteringWorkflowInputs,
)

from products.mcp_analytics.backend import intent_clustering
from products.mcp_analytics.backend.models import MCPIntentClusterSnapshot

logger = structlog.get_logger(__name__)


@database_sync_to_async
def _resolve_team_and_user(team_id: int, user_id: int | None):
    """Look up the team (must exist) and the optional originating user."""
    from posthog.models.user import User

    team = Team.objects.get(pk=team_id)
    user = User.objects.filter(pk=user_id).first() if user_id is not None else None
    return team, user


@database_sync_to_async
def _resolve_canonical_team_id(team_id: int) -> int:
    """Resolve canonical team_id in a thread; team_scope() resolution is sync."""
    from posthog.models.scoping.manager import resolve_effective_team_id

    return resolve_effective_team_id(team_id)


@database_sync_to_async
def _mark_computing(team: Team, user) -> MCPIntentClusterSnapshot:
    snapshot, _ = MCPIntentClusterSnapshot.objects.update_or_create(
        team=team,
        defaults={
            "status": MCPIntentClusterSnapshot.Status.COMPUTING,
            "error_message": "",
            "last_computed_by": user,
        },
    )
    return snapshot


@database_sync_to_async
def _persist_clusters(snapshot: MCPIntentClusterSnapshot, clusters_blob: dict) -> None:
    with transaction.atomic():
        snapshot.clusters = clusters_blob
        snapshot.status = MCPIntentClusterSnapshot.Status.IDLE
        snapshot.error_message = ""
        snapshot.last_computed_at = timezone.now()
        snapshot.save(update_fields=["clusters", "status", "error_message", "last_computed_at", "updated_at"])


@database_sync_to_async
def _mark_error(snapshot: MCPIntentClusterSnapshot, message: str) -> None:
    snapshot.status = MCPIntentClusterSnapshot.Status.ERROR
    snapshot.error_message = message[:5000]
    snapshot.save(update_fields=["status", "error_message", "updated_at"])


@activity.defn
async def compute_intent_clusters_activity(inputs: IntentClusteringWorkflowInputs) -> IntentClusteringResult:
    """Run the full intent clustering pipeline for one team.

    Mirrors the Celery task body, but uses Temporal-native primitives:
    heartbeats keep the worker liveness signal up to date during long
    operations, and the snapshot status machine is updated at each stage
    transition so the UI's poll continues to work.
    """
    canonical_team_id = await _resolve_canonical_team_id(inputs.team_id)
    with team_scope(canonical_team_id, canonical=True):
        async with Heartbeater():
            team, user = await _resolve_team_and_user(inputs.team_id, inputs.user_id)
            snapshot = await _mark_computing(team, user)

            try:
                records, intent_by_session = await database_sync_to_async(intent_clustering.fetch_intent_corpus)(
                    team, lookback_days=inputs.lookback_days, top_n=inputs.top_n
                )
                activity.heartbeat("fetched corpus")

                if not records:
                    await database_sync_to_async(_save_empty_blob)(snapshot)
                    logger.info(
                        "mcpa.intent_clustering.no_intents_found",
                        team_id=inputs.team_id,
                        workflow_id=activity.info().workflow_id,
                    )
                    return IntentClusteringResult(
                        team_id=inputs.team_id, n_intents=0, n_clusters=0, computed_at=timezone.now().isoformat()
                    )

                embeddings, valid_indices = await intent_clustering.embed_intents_async(
                    team, [r.intent_text for r in records]
                )
                if len(valid_indices) == 0:
                    raise RuntimeError("All embedding requests failed")
                activity.heartbeat("embedded")

                aligned_records = [records[i] for i in valid_indices]
                # sklearn AgglomerativeClustering builds an O(n²) distance matrix
                # in pure-Python/numpy — offload so the asyncio loop stays
                # responsive to heartbeats and other activities on this worker.
                labels = await asyncio.to_thread(intent_clustering.cluster_embeddings, embeddings)
                activity.heartbeat("clustered")

                session_journeys = await database_sync_to_async(intent_clustering.fetch_session_journeys)(
                    team, list(intent_by_session.keys()), lookback_days=inputs.lookback_days
                )
                intent_to_sessions: dict[str, list[str]] = {}
                for sid, intent_text in intent_by_session.items():
                    intent_to_sessions.setdefault(intent_text, []).append(sid)
                journeys_by_cluster = intent_clustering.aggregate_journeys_per_cluster(
                    aligned_records, labels, session_journeys, intent_to_sessions
                )
                activity.heartbeat("journeys")

                # Same blocking-loop concern as cluster_embeddings — pure-numpy
                # aggregation over the labelled corpus.
                clusters_blob = await asyncio.to_thread(
                    intent_clustering.build_snapshot,
                    aligned_records,
                    labels,
                    embeddings,
                    journeys_by_cluster=journeys_by_cluster,
                )
                await _persist_clusters(snapshot, clusters_blob)

                n_clusters = len(clusters_blob.get("clusters", []))
                record_intents_analyzed(len(aligned_records))
                record_clusters_generated(n_clusters)
                logger.info(
                    "mcpa.intent_clustering.computed",
                    team_id=inputs.team_id,
                    n_intents=len(aligned_records),
                    n_clusters=n_clusters,
                    workflow_id=activity.info().workflow_id,
                )
                return IntentClusteringResult(
                    team_id=inputs.team_id,
                    n_intents=len(aligned_records),
                    n_clusters=n_clusters,
                    computed_at=timezone.now().isoformat(),
                )

            except Exception as exc:
                logger.exception("mcpa.intent_clustering.failed", team_id=inputs.team_id, error=str(exc))
                await _mark_error(snapshot, str(exc))
                raise


def _save_empty_blob(snapshot: MCPIntentClusterSnapshot) -> None:
    """Synchronous helper to write an empty snapshot when the corpus is empty.

    Lives outside the async activity body so ``database_sync_to_async`` can
    wrap it without re-entrancy from inside an async context.
    """
    snapshot.clusters = {
        "clusters": [],
        "computed_with": {
            "distance_threshold": intent_clustering.DEFAULT_DISTANCE_THRESHOLD,
            "embedding_model": intent_clustering.EMBEDDING_MODEL,
            "n_intents": 0,
            "n_clusters": 0,
        },
    }
    snapshot.status = MCPIntentClusterSnapshot.Status.IDLE
    snapshot.error_message = ""
    snapshot.last_computed_at = timezone.now()
    snapshot.save(update_fields=["clusters", "status", "error_message", "last_computed_at", "updated_at"])
