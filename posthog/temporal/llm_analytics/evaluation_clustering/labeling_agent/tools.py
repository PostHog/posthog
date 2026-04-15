"""Tool definitions for the evaluation cluster-labeling agent.

Parallel to ``trace_clustering.labeling_agent.tools`` — same InjectedState
pattern, same label-setting semantics — but the content-rendering tools
surface evaluation-specific fields (verdict, reasoning, evaluator name)
instead of trace summaries.
"""

import json
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel


def _title_for_eval(eval_id: str, state: dict) -> str:
    """Render the short title the agent sees for an eval in overview passes."""
    content = state["all_eval_contents"].get(eval_id)
    if not content:
        return eval_id
    name = content.get("evaluation_name") or "Evaluation"
    verdict = content.get("verdict") or "unknown"
    return f"{name}: {verdict}"


@tool
def get_clusters_overview(
    state: Annotated[dict, InjectedState],
) -> str:
    """High-level overview: cluster IDs, sizes, and 2D centroid positions.

    Start here to understand what clusters exist and their relative sizes.
    """
    overviews = []
    for cluster_id, cluster_data in state["cluster_data"].items():
        overviews.append(
            {
                "cluster_id": cluster_id,
                "size": cluster_data["size"],
                "centroid_x": cluster_data["centroid_x"],
                "centroid_y": cluster_data["centroid_y"],
            }
        )
    return json.dumps(sorted(overviews, key=lambda x: x["cluster_id"]), indent=2)


@tool
def get_all_clusters_with_sample_titles(
    state: Annotated[dict, InjectedState],
    titles_per_cluster: int = 10,
) -> str:
    """**Recommended for Phase 1.** Get ALL clusters with sample evaluation titles in a single call.

    Each title is rendered as "{evaluator_name}: {verdict}" so the agent can
    quickly see the verdict mix and evaluator names in each cluster. Titles
    are sorted by distance to centroid (most representative first).
    """
    result = []
    for cluster_id, cluster_data in state["cluster_data"].items():
        evals_metadata = cluster_data["evals"]
        sorted_evals = sorted(evals_metadata.items(), key=lambda x: x[1]["rank"])
        sample_titles = [_title_for_eval(eval_id, state) for eval_id, _ in sorted_evals[:titles_per_cluster]]
        result.append(
            {
                "cluster_id": cluster_id,
                "size": cluster_data["size"],
                "sample_titles": sample_titles,
            }
        )
    return json.dumps(sorted(result, key=lambda x: x["cluster_id"]), indent=2)


@tool
def get_cluster_eval_titles(
    state: Annotated[dict, InjectedState],
    cluster_id: int,
    limit: int = 30,
) -> str:
    """Lightweight list of evaluator + verdict titles for one cluster.

    Use this to scan what's in a cluster without pulling full reasoning text.
    ``rank`` indicates distance to centroid (1 = most representative); edge
    ranks may reveal sub-patterns worth drilling into with ``get_eval_details``.
    """
    cluster_data = state["cluster_data"].get(cluster_id)
    if not cluster_data:
        return json.dumps([])

    evals_metadata = cluster_data["evals"]
    infos = []
    for eval_id, metadata in evals_metadata.items():
        infos.append(
            {
                "eval_id": eval_id,
                "title": _title_for_eval(eval_id, state),
                "rank": metadata["rank"],
                "distance_to_centroid": metadata["distance_to_centroid"],
                "x": metadata["x"],
                "y": metadata["y"],
            }
        )
    infos.sort(key=lambda x: x["rank"])
    return json.dumps(infos[:limit], indent=2)


@tool
def get_eval_details(
    state: Annotated[dict, InjectedState],
    eval_ids: list[str],
) -> str:
    """Get full evaluation details including reasoning, runtime, and linked generation metadata.

    Use strategically on evaluations you want to examine closely — more
    expensive than the titles call because it includes the full reasoning text.
    """
    details = []
    contents = state["all_eval_contents"]
    for eval_id in eval_ids:
        content = contents.get(eval_id)
        if not content:
            continue
        details.append(
            {
                "eval_id": eval_id,
                "evaluation_name": content.get("evaluation_name"),
                "verdict": content.get("verdict"),
                "reasoning": content.get("reasoning"),
                "runtime": content.get("runtime"),
                "generation_model": content.get("generation_model"),
                "is_error": content.get("is_error"),
                "judge_cost_usd": content.get("judge_cost_usd"),
            }
        )
    return json.dumps(details, indent=2)


@tool
def get_current_labels(
    state: Annotated[dict, InjectedState],
) -> str:
    """Review all cluster labels set so far; useful for distinctiveness checks."""
    result: dict[int, dict[str, str] | None] = {}
    for cluster_id in state["cluster_data"].keys():
        label = state["current_labels"].get(cluster_id)
        if label:
            result[cluster_id] = {"title": label.title, "description": label.description}
        else:
            result[cluster_id] = None
    return json.dumps(result, indent=2)


@tool
def set_cluster_label(
    state: Annotated[dict, InjectedState],
    cluster_id: int,
    title: str,
    description: str,
) -> str:
    """Set or update the label for a specific cluster.

    Title should be 3-10 words naming the shared evaluation pattern (e.g.
    "Factuality failures on multi-hop questions"). Description should be 2-5
    bullet points explaining what the evaluations have in common —
    the failure mode, the evaluator rationale, the kind of generation input
    they target.
    """
    state["current_labels"][cluster_id] = ClusterLabel(title=title, description=description)
    return f"Label set for cluster {cluster_id}: '{title}'"


@tool
def bulk_set_labels(
    state: Annotated[dict, InjectedState],
    labels: list[dict],
) -> str:
    """Set initial labels for many clusters in one call.

    Use this in Phase 1 so every cluster has at least a rough label before
    refinement begins.
    """
    for entry in labels:
        cluster_id = entry["cluster_id"]
        state["current_labels"][cluster_id] = ClusterLabel(
            title=entry["title"],
            description=entry["description"],
        )
    return f"Labels set for {len(labels)} clusters: {[e['cluster_id'] for e in labels]}"


@tool
def finalize_labels(
    state: Annotated[dict, InjectedState],
) -> str:
    """Signal that every cluster has a satisfactory, distinctive label."""
    labeled_count = sum(1 for label in state["current_labels"].values() if label is not None)
    total_count = len(state["cluster_data"])
    return f"Finalized! {labeled_count}/{total_count} clusters labeled."


EVAL_LABELING_TOOLS = [
    get_clusters_overview,
    get_all_clusters_with_sample_titles,
    get_cluster_eval_titles,
    get_eval_details,
    get_current_labels,
    set_cluster_label,
    bulk_set_labels,
    finalize_labels,
]
