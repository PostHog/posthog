"""Tool definitions for the cluster labeling agent.

Uses LangGraph's InjectedState pattern so tools can access graph state directly.
This eliminates the need for separate execution functions and manual tool dispatch.
"""

import json
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel


@tool
def get_clusters_overview(
    state: Annotated[dict, InjectedState],
) -> str:
    """Get a high-level overview of all clusters including their IDs, sizes, and centroid positions.

    Use this tool first to understand what clusters exist and how large they are.
    Returns a list of cluster overviews with cluster_id, size, centroid_x, and centroid_y.
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
    """Get all clusters with sample trace titles in a single call. **Use this for Phase 1 initial labeling.**

    This is the most efficient way to get a global overview for initial labeling.
    Returns all clusters with their sizes and sample trace titles (sorted by distance to centroid).

    Args:
        titles_per_cluster: Number of sample titles to return per cluster (default 10)
    """
    result = []
    trace_summaries = state["all_trace_summaries"]

    for cluster_id, cluster_data in state["cluster_data"].items():
        traces_metadata = cluster_data["traces"]

        # Get traces sorted by rank (closest to centroid first)
        sorted_traces = sorted(traces_metadata.items(), key=lambda x: x[1]["rank"])

        # Extract just the titles
        sample_titles = []
        for trace_id, _ in sorted_traces[:titles_per_cluster]:
            summary = trace_summaries.get(trace_id)
            title = summary.get("title", "Untitled") if summary else "Untitled"
            sample_titles.append(title)

        result.append(
            {
                "cluster_id": cluster_id,
                "size": cluster_data["size"],
                "sample_titles": sample_titles,
            }
        )

    return json.dumps(sorted(result, key=lambda x: x["cluster_id"]), indent=2)


@tool
def get_cluster_trace_titles(
    state: Annotated[dict, InjectedState],
    cluster_id: int,
    limit: int = 30,
) -> str:
    """Get a lightweight list of trace titles and metadata for a specific cluster.

    Use this to scan what traces are in a cluster without loading full summaries.
    Returns trace_id, title, rank (1=closest to centroid), distance_to_centroid, x, y.
    The rank helps identify core vs edge traces.

    Args:
        cluster_id: The cluster ID to get trace titles for
        limit: Maximum number of traces to return (default 30)
    """
    cluster_data = state["cluster_data"].get(cluster_id)
    if not cluster_data:
        return json.dumps([])

    trace_summaries = state["all_trace_summaries"]
    traces_metadata = cluster_data["traces"]

    title_infos = []
    for trace_id, metadata in traces_metadata.items():
        summary = trace_summaries.get(trace_id)
        title_infos.append(
            {
                "trace_id": trace_id,
                "title": summary.get("title", "Untitled") if summary else "Untitled",
                "rank": metadata["rank"],
                "distance_to_centroid": metadata["distance_to_centroid"],
                "x": metadata["x"],
                "y": metadata["y"],
            }
        )

    # Sort by rank (closest to centroid first) and limit
    title_infos.sort(key=lambda x: x["rank"])
    return json.dumps(title_infos[:limit], indent=2)


@tool
def get_trace_details(
    state: Annotated[dict, InjectedState],
    trace_ids: list[str],
) -> str:
    """Get full trace summaries including title, flow diagram, summary bullets, and interesting notes.

    Use this strategically for specific traces you want to examine in detail.
    More expensive than get_cluster_trace_titles, so use selectively.

    Args:
        trace_ids: List of trace IDs to get full details for
    """
    details = []
    trace_summaries = state["all_trace_summaries"]

    for trace_id in trace_ids:
        summary = trace_summaries.get(trace_id)
        if summary:
            details.append(
                {
                    "trace_id": trace_id,
                    "title": summary.get("title", "Untitled"),
                    "flow_diagram": summary.get("flow_diagram", ""),
                    "bullets": summary.get("bullets", ""),
                    "interesting_notes": summary.get("interesting_notes", ""),
                }
            )
    return json.dumps(details, indent=2)


@tool
def get_current_labels(
    state: Annotated[dict, InjectedState],
) -> str:
    """Get all cluster labels that have been set so far.

    Use this to review all labels together and check for distinctiveness.
    Returns a dict mapping cluster_id to {title, description} or null if not yet labeled.
    """
    result = {}
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

    Args:
        cluster_id: The cluster ID to set the label for
        title: The title for the cluster (3-10 words, be specific not generic)
        description: The description as 2-5 bullet points explaining what makes this cluster unique
    """
    state["current_labels"][cluster_id] = ClusterLabel(title=title, description=description)
    return f"Label set for cluster {cluster_id}: '{title}'"


@tool
def bulk_set_labels(
    state: Annotated[dict, InjectedState],
    labels: list[dict],
) -> str:
    """Set labels for multiple clusters at once. Use this to quickly set initial labels for all clusters.

    This is more efficient than calling set_cluster_label multiple times.
    Use this in your first pass to ensure all clusters have at least initial labels,
    then refine individual labels as needed.

    Args:
        labels: List of objects with cluster_id, title, and description fields
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
    """Signal that all clusters have been labeled and you are done.

    Only call this when all clusters have satisfactory, distinctive labels.
    After calling this, no more tool calls will be processed.
    """
    labeled_count = sum(1 for label in state["current_labels"].values() if label is not None)
    total_count = len(state["cluster_data"])
    return f"Finalized! {labeled_count}/{total_count} clusters labeled."


# List of all tools for binding to the agent
LABELING_TOOLS = [
    get_clusters_overview,
    get_all_clusters_with_sample_titles,
    get_cluster_trace_titles,
    get_trace_details,
    get_current_labels,
    set_cluster_label,
    bulk_set_labels,
    finalize_labels,
]
