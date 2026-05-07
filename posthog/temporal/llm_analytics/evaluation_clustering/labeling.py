"""High-level labeling entry point for evaluation clustering.

Converts the compute-activity outputs (items, labels, per-item metadata,
centroid 2D coords) and the eval metadata map into the shapes the LangGraph
labeling agent expects, then invokes it.
"""

import numpy as np

from posthog.temporal.llm_analytics.evaluation_clustering.data import EvaluationMetadata
from posthog.temporal.llm_analytics.evaluation_clustering.labeling_agent import run_eval_labeling_agent
from posthog.temporal.llm_analytics.evaluation_clustering.labeling_agent.state import (
    ClusterEvalData,
    EvalContent,
    EvalMetadata,
)
from posthog.temporal.llm_analytics.trace_clustering.constants import NOISE_CLUSTER_ID
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterItem, ClusterLabel, TraceLabelingMetadata


def generate_evaluation_cluster_labels(
    team_id: int,
    items: list[ClusterItem],
    labels: list[int],
    item_metadata: list[TraceLabelingMetadata],
    centroid_coords_2d: list[list[float]],
    eval_metadata: dict[str, EvaluationMetadata],
    window_start: str,
    window_end: str,
) -> dict[int, ClusterLabel]:
    """Build eval-agent inputs from compute outputs and run the labeling agent."""
    labels_array = np.array(labels)
    unique_cluster_ids = np.unique(labels_array)

    cluster_data = _build_eval_cluster_data(
        items=items,
        labels=labels_array,
        item_metadata=item_metadata,
        centroid_coords_2d=centroid_coords_2d,
        unique_cluster_ids=unique_cluster_ids,
        eval_metadata=eval_metadata,
    )

    all_eval_contents = _build_eval_contents(items=items, eval_metadata=eval_metadata)

    return run_eval_labeling_agent(
        team_id=team_id,
        cluster_data=cluster_data,
        all_eval_contents=all_eval_contents,
        window_start=window_start,
        window_end=window_end,
    )


def _derive_verdict(meta: EvaluationMetadata | None) -> str:
    if meta is None:
        return "unknown"
    if meta.evaluation_applicable is False:
        return "n/a"
    if meta.evaluation_result is True:
        return "pass"
    if meta.evaluation_result is False:
        return "fail"
    return "unknown"


def _build_eval_contents(
    items: list[ClusterItem],
    eval_metadata: dict[str, EvaluationMetadata],
) -> dict[str, EvalContent]:
    """Keyed by eval_id; eval_id lives in each ``ClusterItem.generation_id`` slot.

    The eval compute activity puts the $ai_evaluation event UUID in the
    ``generation_id`` field so the cluster member dicts use the same shape as
    generation-level clusters. The linked generation (target_generation_id)
    and parent trace are carried through separately on ``EvaluationMetadata``.
    """
    contents: dict[str, EvalContent] = {}
    for item in items:
        eval_id = item.generation_id or item.trace_id
        meta = eval_metadata.get(eval_id)
        contents[eval_id] = EvalContent(
            evaluation_id=meta.evaluation_id if meta else None,
            evaluation_name=meta.evaluation_name if meta else None,
            verdict=_derive_verdict(meta),
            reasoning=meta.evaluation_reasoning if meta else None,
            runtime=meta.evaluation_runtime if meta else None,
            generation_model=meta.generation_model if meta else None,
            is_error=meta.generation_is_error if meta else None,
            judge_cost_usd=meta.judge_cost_usd if meta else None,
            target_generation_id=meta.target_generation_id if meta else None,
        )
    return contents


def _build_eval_cluster_data(
    items: list[ClusterItem],
    labels: np.ndarray,
    item_metadata: list[TraceLabelingMetadata],
    centroid_coords_2d: list[list[float]],
    unique_cluster_ids: np.ndarray,
    eval_metadata: dict[str, EvaluationMetadata],
) -> dict[int, ClusterEvalData]:
    """Mirror of ``trace_clustering.labeling._build_cluster_data`` for evaluations.

    Title is rendered here instead of being filled at agent time so the tools
    don't need to know the verdict-derivation rules.
    """
    cluster_data: dict[int, ClusterEvalData] = {}
    centroid_coords = np.array(centroid_coords_2d) if centroid_coords_2d else np.zeros((0, 2))

    non_noise_ids = sorted([int(cid) for cid in unique_cluster_ids if cid != NOISE_CLUSTER_ID])
    cluster_to_centroid_idx = {cid: idx for idx, cid in enumerate(non_noise_ids)}

    for cluster_id in unique_cluster_ids:
        cluster_id_int = int(cluster_id)
        cluster_mask = labels == cluster_id
        cluster_item_indices = np.where(cluster_mask)[0]
        cluster_size = len(cluster_item_indices)
        if cluster_size == 0:
            continue

        if cluster_id == NOISE_CLUSTER_ID:
            centroid_x = float(np.mean([item_metadata[i].x for i in cluster_item_indices]))
            centroid_y = float(np.mean([item_metadata[i].y for i in cluster_item_indices]))
        else:
            centroid_idx = cluster_to_centroid_idx.get(cluster_id_int)
            if centroid_idx is not None and centroid_idx < len(centroid_coords):
                centroid_x = float(centroid_coords[centroid_idx, 0])
                centroid_y = float(centroid_coords[centroid_idx, 1])
            else:
                centroid_x = float(np.mean([item_metadata[i].x for i in cluster_item_indices]))
                centroid_y = float(np.mean([item_metadata[i].y for i in cluster_item_indices]))

        evals_metadata: dict[str, EvalMetadata] = {}
        for item_idx in cluster_item_indices:
            item = items[item_idx]
            eval_id = item.generation_id or item.trace_id
            meta = eval_metadata.get(eval_id)
            evaluator_name = (meta.evaluation_name if meta else None) or "Evaluation"
            verdict = _derive_verdict(meta)
            title = f"{evaluator_name}: {verdict}"

            meta_for_label = item_metadata[item_idx]
            evals_metadata[eval_id] = EvalMetadata(
                eval_id=eval_id,
                title=title,
                rank=meta_for_label.rank,
                distance_to_centroid=meta_for_label.distance_to_centroid,
                x=meta_for_label.x,
                y=meta_for_label.y,
            )

        cluster_data[cluster_id_int] = ClusterEvalData(
            cluster_id=cluster_id_int,
            size=cluster_size,
            centroid_x=centroid_x,
            centroid_y=centroid_y,
            evals=evals_metadata,
        )

    return cluster_data
