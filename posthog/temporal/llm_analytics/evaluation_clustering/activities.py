"""Temporal activities for Stage B evaluation clustering.

Pipeline:

1. ``perform_evaluation_clustering_compute_activity`` — fetch accumulated eval
   embeddings for the job, HDBSCAN, distances, 2D coords. Returns lightweight
   metadata; the 3072-dim embeddings stay inside this activity.
2. ``fetch_evaluation_metadata_activity`` — for the sampled eval ids, join
   $ai_evaluation → linked $ai_generation and return combined eval + generation
   metadata.
3. ``generate_evaluation_cluster_labels_activity`` — LangGraph agent.
4. ``compute_evaluation_cluster_aggregates_activity`` — per-cluster operational
   + eval-specific metrics.
5. ``emit_evaluation_cluster_events_activity`` — $ai_evaluation_clusters event.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from django.utils.dateparse import parse_datetime

import numpy as np
import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.llm_analytics.evaluation_clustering.aggregates import aggregate_evaluation_metrics
from posthog.temporal.llm_analytics.evaluation_clustering.constants import (
    CLUSTERING_MAX_SAMPLES,
    MIN_EMBEDDINGS_FOR_CLUSTERING,
)
from posthog.temporal.llm_analytics.evaluation_clustering.data import (
    EvaluationMetadata,
    fetch_evaluation_embeddings,
    fetch_evaluation_metadata,
)
from posthog.temporal.llm_analytics.evaluation_clustering.event_emission import emit_evaluation_cluster_events
from posthog.temporal.llm_analytics.evaluation_clustering.labeling import generate_evaluation_cluster_labels
from posthog.temporal.llm_analytics.trace_clustering import constants as trace_constants
from posthog.temporal.llm_analytics.trace_clustering.clustering import (
    calculate_distances_to_cluster_means,
    compute_2d_coordinates,
    perform_hdbscan_clustering,
    reduce_dimensions_for_clustering,
)
from posthog.temporal.llm_analytics.trace_clustering.models import (
    ClusterAggregateMetrics,
    ClusteringMetrics,
    ClusteringParams,
    ClusteringResult,
    ClusterItem,
    ClusterLabel,
    TraceLabelingMetadata,
)

logger = structlog.get_logger(__name__)


# ---- Activity input/output dataclasses ----


@dataclass
class EvaluationClusteringComputeInputs:
    team_id: int
    job_id: str
    job_name: str
    max_samples: int = CLUSTERING_MAX_SAMPLES
    embedding_normalization: str = "l2"
    dimensionality_reduction_method: str = "umap"
    dimensionality_reduction_ndims: int = trace_constants.DEFAULT_UMAP_N_COMPONENTS
    visualization_method: str = "umap"
    clustering_method_params: dict[str, Any] = field(default_factory=dict)
    run_label: str = ""

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "job_id": self.job_id}


@dataclass
class EvaluationClusteringComputeResult:
    clustering_run_id: str
    eval_ids: list[str]
    labels: list[int]
    centroids: list[list[float]]
    distances: list[list[float]]
    coords_2d: list[list[float]]
    centroid_coords_2d: list[list[float]]
    num_noise_points: int = 0
    skip_reason: str | None = None  # Set when there weren't enough embeddings


@dataclass
class FetchEvaluationMetadataInputs:
    team_id: int
    eval_ids: list[str]
    window_start: str
    window_end: str


@dataclass
class FetchEvaluationMetadataResult:
    """Serializable wrapper — Temporal needs a concrete dataclass here."""

    metadata: dict[str, EvaluationMetadata]


@dataclass
class GenerateEvaluationLabelsInputs:
    team_id: int
    eval_ids: list[str]
    labels: list[int]
    item_metadata: list[TraceLabelingMetadata]
    centroid_coords_2d: list[list[float]]
    eval_metadata: dict[str, EvaluationMetadata]


@dataclass
class GenerateEvaluationLabelsOutputs:
    cluster_labels: dict[int, ClusterLabel]


@dataclass
class ComputeEvaluationAggregatesInputs:
    eval_ids: list[str]
    labels: list[int]
    eval_metadata: dict[str, EvaluationMetadata]


@dataclass
class EmitEvaluationClusterEventsInputs:
    team_id: int
    clustering_run_id: str
    window_start: str
    window_end: str
    eval_ids: list[str]
    labels: list[int]
    centroids: list[list[float]]
    distances: list[list[float]]
    coords_2d: list[list[float]]
    centroid_coords_2d: list[list[float]]
    cluster_labels: dict[int, ClusterLabel]
    eval_metadata: dict[str, EvaluationMetadata]
    clustering_params: ClusteringParams | None = None
    job_id: str = ""
    job_name: str = ""
    cluster_metrics: dict[int, ClusterAggregateMetrics] = field(default_factory=dict)


# ---- Activities ----


def _items_from_eval_ids(eval_ids: list[str]) -> list[ClusterItem]:
    """Stuff each eval event uuid into ClusterItem.generation_id.

    The spec treats each eval cluster member as a "generation-with-eval pairing";
    downstream emission and labeling use ``generation_id`` as the per-item key
    so we slot the eval uuid there. The actual linked generation + parent trace
    come from the metadata join and aren't needed until emission.
    """
    return [ClusterItem(trace_id=eval_id, generation_id=eval_id) for eval_id in eval_ids]


def _compute_sync(inputs: EvaluationClusteringComputeInputs) -> EvaluationClusteringComputeResult:
    team = Team.objects.get(id=inputs.team_id)

    base_run_id = f"{inputs.team_id}_evaluation_{inputs.job_id}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    clustering_run_id = f"{base_run_id}_{inputs.run_label}" if inputs.run_label else base_run_id

    eval_ids, embeddings_map = fetch_evaluation_embeddings(
        team=team,
        job_id=inputs.job_id,
        max_samples=inputs.max_samples,
    )

    if len(eval_ids) < MIN_EMBEDDINGS_FOR_CLUSTERING:
        logger.warning(
            "Not enough eval embeddings accumulated yet",
            job_id=inputs.job_id,
            team_id=inputs.team_id,
            count=len(eval_ids),
            min_required=MIN_EMBEDDINGS_FOR_CLUSTERING,
        )
        return EvaluationClusteringComputeResult(
            clustering_run_id=clustering_run_id,
            eval_ids=[],
            labels=[],
            centroids=[],
            distances=[],
            coords_2d=[],
            centroid_coords_2d=[],
            num_noise_points=0,
            skip_reason="not_enough_embeddings",
        )

    embeddings_array = np.array([embeddings_map[eid] for eid in eval_ids])

    if inputs.embedding_normalization == "l2":
        norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        embeddings_array = embeddings_array / norms

    # UMAP to reduce dimensions for HDBSCAN
    if inputs.dimensionality_reduction_method == "umap":
        clustering_embeddings, _ = reduce_dimensions_for_clustering(
            embeddings_array,
            n_components=inputs.dimensionality_reduction_ndims,
            n_neighbors=trace_constants.DEFAULT_UMAP_N_NEIGHBORS,
            min_dist=trace_constants.DEFAULT_UMAP_MIN_DIST,
        )
    else:
        clustering_embeddings = embeddings_array

    params = inputs.clustering_method_params or {}
    hdbscan_result = perform_hdbscan_clustering(
        clustering_embeddings,
        min_cluster_size_fraction=params.get(
            "min_cluster_size_fraction", trace_constants.DEFAULT_MIN_CLUSTER_SIZE_FRACTION
        ),
        min_samples=params.get("min_samples", trace_constants.DEFAULT_HDBSCAN_MIN_SAMPLES),
    )
    labels_array = np.array(hdbscan_result.labels)
    centroids_array = (
        np.array(hdbscan_result.centroids)
        if hdbscan_result.centroids
        else np.zeros((0, clustering_embeddings.shape[1]))
    )

    distances_matrix = calculate_distances_to_cluster_means(clustering_embeddings, labels_array, centroids_array)
    coords_2d, centroid_coords_2d = compute_2d_coordinates(
        clustering_embeddings,
        centroids_array,
        method=cast(Literal["umap", "pca", "tsne"], inputs.visualization_method),
    )

    return EvaluationClusteringComputeResult(
        clustering_run_id=clustering_run_id,
        eval_ids=eval_ids,
        labels=hdbscan_result.labels,
        centroids=hdbscan_result.centroids,
        distances=distances_matrix.tolist(),
        coords_2d=coords_2d.tolist(),
        centroid_coords_2d=centroid_coords_2d.tolist(),
        num_noise_points=hdbscan_result.num_noise_points,
        skip_reason=None,
    )


@activity.defn
async def perform_evaluation_clustering_compute_activity(
    inputs: EvaluationClusteringComputeInputs,
) -> EvaluationClusteringComputeResult:
    """Fetch embeddings, run HDBSCAN, produce 2D coords — CPU-bound."""
    async with Heartbeater():
        return await database_sync_to_async(_compute_sync, thread_sensitive=False)(inputs)


def _fetch_metadata_sync(inputs: FetchEvaluationMetadataInputs) -> FetchEvaluationMetadataResult:
    team = Team.objects.get(id=inputs.team_id)
    window_start = parse_datetime(inputs.window_start)
    window_end = parse_datetime(inputs.window_end)
    if window_start is None or window_end is None:
        raise ValueError(f"Invalid datetime: {inputs.window_start}, {inputs.window_end}")

    metadata = fetch_evaluation_metadata(
        team=team,
        eval_event_ids=inputs.eval_ids,
        window_start=window_start,
        window_end=window_end,
    )
    return FetchEvaluationMetadataResult(metadata=metadata)


@activity.defn
async def fetch_evaluation_metadata_activity(
    inputs: FetchEvaluationMetadataInputs,
) -> FetchEvaluationMetadataResult:
    async with Heartbeater():
        return await database_sync_to_async(_fetch_metadata_sync, thread_sensitive=False)(inputs)


def _label_sync(inputs: GenerateEvaluationLabelsInputs) -> GenerateEvaluationLabelsOutputs:
    items = _items_from_eval_ids(inputs.eval_ids)
    labels = generate_evaluation_cluster_labels(
        team_id=inputs.team_id,
        items=items,
        labels=inputs.labels,
        item_metadata=inputs.item_metadata,
        centroid_coords_2d=inputs.centroid_coords_2d,
        eval_metadata=inputs.eval_metadata,
    )
    return GenerateEvaluationLabelsOutputs(cluster_labels=labels)


@activity.defn
async def generate_evaluation_cluster_labels_activity(
    inputs: GenerateEvaluationLabelsInputs,
) -> GenerateEvaluationLabelsOutputs:
    async with Heartbeater():
        return await database_sync_to_async(_label_sync, thread_sensitive=False)(inputs)


def _aggregates_sync(inputs: ComputeEvaluationAggregatesInputs) -> dict[int, ClusterAggregateMetrics]:
    return aggregate_evaluation_metrics(
        eval_event_ids=inputs.eval_ids,
        labels=inputs.labels,
        metadata=inputs.eval_metadata,
    )


@activity.defn
async def compute_evaluation_cluster_aggregates_activity(
    inputs: ComputeEvaluationAggregatesInputs,
) -> dict[int, ClusterAggregateMetrics]:
    async with Heartbeater():
        return await database_sync_to_async(_aggregates_sync, thread_sensitive=False)(inputs)


def _emit_sync(inputs: EmitEvaluationClusterEventsInputs) -> ClusteringResult:
    items = _items_from_eval_ids(inputs.eval_ids)
    # Timestamps: eval events have their own timestamps. The simplest reliable
    # approach is to use the linked generation's window_end as a proxy — the
    # cluster view only needs an ISO string for navigation/sorting, not precise
    # per-event timestamps. For a proper per-item timestamp we'd extend the
    # metadata query; keeping it as window_end here keeps the emit path cheap.
    item_timestamps: dict[str, str] = dict.fromkeys(inputs.eval_ids, inputs.window_end)

    clusters = emit_evaluation_cluster_events(
        team_id=inputs.team_id,
        clustering_run_id=inputs.clustering_run_id,
        window_start=inputs.window_start,
        window_end=inputs.window_end,
        labels=inputs.labels,
        centroids=inputs.centroids,
        items=items,
        distances_matrix=np.array(inputs.distances),
        cluster_labels=inputs.cluster_labels,
        coords_2d=np.array(inputs.coords_2d),
        centroid_coords_2d=np.array(inputs.centroid_coords_2d),
        item_timestamps=item_timestamps,
        clustering_params=inputs.clustering_params,
        job_id=inputs.job_id,
        job_name=inputs.job_name,
        cluster_metrics=inputs.cluster_metrics,
    )

    return ClusteringResult(
        clustering_run_id=inputs.clustering_run_id,
        team_id=inputs.team_id,
        timestamp=inputs.window_end,
        window_start=inputs.window_start,
        window_end=inputs.window_end,
        metrics=ClusteringMetrics(
            total_items_analyzed=len(inputs.eval_ids),
            num_clusters=len(inputs.centroids),
        ),
        clusters=clusters,
    )


@activity.defn
async def emit_evaluation_cluster_events_activity(
    inputs: EmitEvaluationClusterEventsInputs,
) -> ClusteringResult:
    async with Heartbeater():
        return await database_sync_to_async(_emit_sync, thread_sensitive=False)(inputs)


# ---- Helpers reused by the workflow ----


def compute_item_labeling_metadata(compute_result: EvaluationClusteringComputeResult) -> list[TraceLabelingMetadata]:
    """Compute per-item (distance, rank, x, y) metadata for the labeler.

    Same idea as ``trace_clustering.workflow._compute_item_labeling_metadata``;
    inlined here to avoid creating a coupling just for this helper.
    """
    labels = np.array(compute_result.labels)
    distances = np.array(compute_result.distances)
    coords_2d = np.array(compute_result.coords_2d)

    n_items = len(labels)
    unique_labels = np.unique(labels)
    non_noise_ids = sorted([cid for cid in unique_labels if cid != trace_constants.NOISE_CLUSTER_ID])
    cluster_to_col = {cid: idx for idx, cid in enumerate(non_noise_ids)}

    item_distances = np.zeros(n_items)
    for i, label in enumerate(labels):
        if label == trace_constants.NOISE_CLUSTER_ID:
            item_distances[i] = 0.0
        else:
            col = cluster_to_col.get(label, 0)
            if col < distances.shape[1]:
                item_distances[i] = distances[i, col]

    noise_mask = labels == trace_constants.NOISE_CLUSTER_ID
    if noise_mask.any() and coords_2d.size:
        noise_coords = coords_2d[noise_mask]
        noise_centroid = noise_coords.mean(axis=0)
        noise_distances = np.linalg.norm(noise_coords - noise_centroid, axis=1)
        item_distances[noise_mask] = noise_distances

    ranks = np.zeros(n_items, dtype=int)
    for cluster_id in unique_labels:
        cluster_mask = labels == cluster_id
        cluster_indices = np.where(cluster_mask)[0]
        cluster_dists = item_distances[cluster_indices]
        order = np.argsort(cluster_dists)
        cluster_ranks = np.empty_like(order)
        cluster_ranks[order] = np.arange(1, len(order) + 1)
        ranks[cluster_indices] = cluster_ranks

    return [
        TraceLabelingMetadata(
            x=float(coords_2d[i, 0]) if coords_2d.size else 0.0,
            y=float(coords_2d[i, 1]) if coords_2d.size else 0.0,
            distance_to_centroid=float(item_distances[i]),
            rank=int(ranks[i]),
        )
        for i in range(n_items)
    ]


# Metadata-query window: eval embeddings accumulated over ~24h, so the metadata
# fetch needs a slightly wider window than the Stage A sampler window. Using 3
# days from now buys extra safety for late-arriving evals.
METADATA_LOOKBACK = timedelta(days=3)
