"""Tool definitions for the cluster labeling agent.

These tools allow the agent to explore cluster structure and generate labels.
Tools are implemented as functions that will be called by the tools node with
the appropriate state data.
"""

from typing import Any

from langchain_core.tools import tool

from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.state import (
    ClusterLabelingState,
    ClusterOverview,
    ClusterWithSampleTitles,
    LabelInfo,
    TraceDetail,
    TraceTitleInfo,
)
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel

# Tool definitions using @tool decorator
# These are the schemas that will be bound to the LLM.
# The actual execution logic is in the execute_* functions below.


@tool
def get_clusters_overview() -> str:
    """Get a high-level overview of all clusters including their IDs, sizes, and centroid positions.

    Use this tool first to understand what clusters exist and how large they are.
    Returns a list of cluster overviews with cluster_id, size, centroid_x, and centroid_y.
    """
    # This tool takes no input - execution handled by tools node
    return "Executed by tools node"


@tool
def get_all_clusters_with_sample_titles(titles_per_cluster: int = 10) -> str:
    """Get all clusters with sample trace titles in a single call. **Use this for Phase 1 initial labeling.**

    This is the most efficient way to get a global overview for initial labeling.
    Returns all clusters with their sizes and sample trace titles (sorted by distance to centroid).

    Args:
        titles_per_cluster: Number of sample titles to return per cluster (default 10)
    """
    return "Executed by tools node"


@tool
def get_cluster_trace_titles(cluster_id: int, limit: int = 30) -> str:
    """Get a lightweight list of trace titles and metadata for a specific cluster.

    Use this to scan what traces are in a cluster without loading full summaries.
    Returns trace_id, title, rank (1=closest to centroid), distance_to_centroid, x, y.
    The rank helps identify core vs edge traces.

    Args:
        cluster_id: The cluster ID to get trace titles for
        limit: Maximum number of traces to return (default 30)
    """
    return "Executed by tools node"


@tool
def get_trace_details(trace_ids: list[str]) -> str:
    """Get full trace summaries including title, flow diagram, summary bullets, and interesting notes.

    Use this strategically for specific traces you want to examine in detail.
    More expensive than get_cluster_trace_titles, so use selectively.

    Args:
        trace_ids: List of trace IDs to get full details for
    """
    return "Executed by tools node"


@tool
def get_current_labels() -> str:
    """Get all cluster labels that have been set so far.

    Use this to review all labels together and check for distinctiveness.
    Returns a dict mapping cluster_id to {title, description} or null if not yet labeled.
    """
    return "Executed by tools node"


@tool
def set_cluster_label(cluster_id: int, title: str, description: str) -> str:
    """Set or update the label for a specific cluster.

    Args:
        cluster_id: The cluster ID to set the label for
        title: The title for the cluster (3-10 words, be specific not generic)
        description: The description as 2-5 bullet points explaining what makes this cluster unique
    """
    return "Executed by tools node"


@tool
def bulk_set_labels(labels: list[dict]) -> str:
    """Set labels for multiple clusters at once. Use this to quickly set initial labels for all clusters.

    This is more efficient than calling set_cluster_label multiple times.
    Use this in your first pass to ensure all clusters have at least initial labels,
    then refine individual labels as needed.

    Args:
        labels: List of objects with cluster_id, title, and description fields
    """
    return "Executed by tools node"


@tool
def finalize_labels() -> str:
    """Signal that all clusters have been labeled and you are done.

    Only call this when all clusters have satisfactory, distinctive labels.
    After calling this, no more tool calls will be processed.
    """
    return "Executed by tools node"


# Tool execution functions - called by the tools node with state


def execute_get_clusters_overview(state: ClusterLabelingState) -> list[ClusterOverview]:
    """Execute get_clusters_overview tool with state."""
    overviews: list[ClusterOverview] = []
    for cluster_id, cluster_data in state["cluster_data"].items():
        overviews.append(
            ClusterOverview(
                cluster_id=cluster_id,
                size=cluster_data["size"],
                centroid_x=cluster_data["centroid_x"],
                centroid_y=cluster_data["centroid_y"],
            )
        )
    # Sort by cluster_id for consistent ordering
    return sorted(overviews, key=lambda x: x["cluster_id"])


def execute_get_all_clusters_with_sample_titles(
    state: ClusterLabelingState, titles_per_cluster: int = 10
) -> list[ClusterWithSampleTitles]:
    """Execute get_all_clusters_with_sample_titles tool with state.

    Returns all clusters with sample trace titles in a single response.
    """
    result: list[ClusterWithSampleTitles] = []
    trace_summaries = state["all_trace_summaries"]

    for cluster_id, cluster_data in state["cluster_data"].items():
        traces_metadata = cluster_data["traces"]

        # Get traces sorted by rank (closest to centroid first)
        sorted_traces = sorted(traces_metadata.items(), key=lambda x: x[1]["rank"])

        # Extract just the titles
        sample_titles: list[str] = []
        for trace_id, _ in sorted_traces[:titles_per_cluster]:
            summary: dict[str, str] = trace_summaries.get(trace_id, {})
            title = summary.get("title", "Untitled")
            sample_titles.append(title)

        result.append(
            ClusterWithSampleTitles(
                cluster_id=cluster_id,
                size=cluster_data["size"],
                sample_titles=sample_titles,
            )
        )

    # Sort by cluster_id for consistent ordering
    return sorted(result, key=lambda x: x["cluster_id"])


def execute_get_cluster_trace_titles(
    state: ClusterLabelingState, cluster_id: int, limit: int = 30
) -> list[TraceTitleInfo]:
    """Execute get_cluster_trace_titles tool with state."""
    cluster_data = state["cluster_data"].get(cluster_id)
    if not cluster_data:
        return []

    trace_summaries = state["all_trace_summaries"]
    traces_metadata = cluster_data["traces"]

    # Build list of trace title info
    title_infos: list[TraceTitleInfo] = []
    for trace_id, metadata in traces_metadata.items():
        summary: dict[str, str] = trace_summaries.get(trace_id, {})
        title_infos.append(
            TraceTitleInfo(
                trace_id=trace_id,
                title=summary.get("title", "Untitled"),
                rank=metadata["rank"],
                distance_to_centroid=metadata["distance_to_centroid"],
                x=metadata["x"],
                y=metadata["y"],
            )
        )

    # Sort by rank (closest to centroid first) and limit
    title_infos.sort(key=lambda x: x["rank"])
    return title_infos[:limit]


def execute_get_trace_details(state: ClusterLabelingState, trace_ids: list[str]) -> list[TraceDetail]:
    """Execute get_trace_details tool with state."""
    details: list[TraceDetail] = []
    trace_summaries = state["all_trace_summaries"]

    for trace_id in trace_ids:
        summary = trace_summaries.get(trace_id)
        if summary:
            details.append(
                TraceDetail(
                    trace_id=trace_id,
                    title=summary.get("title", "Untitled"),
                    flow_diagram=summary.get("flow_diagram", ""),
                    bullets=summary.get("bullets", ""),
                    interesting_notes=summary.get("interesting_notes", ""),
                )
            )
    return details


def execute_get_current_labels(state: ClusterLabelingState) -> dict[int, LabelInfo | None]:
    """Execute get_current_labels tool with state."""
    result: dict[int, LabelInfo | None] = {}

    # Include all cluster IDs from cluster_data
    for cluster_id in state["cluster_data"].keys():
        label = state["current_labels"].get(cluster_id)
        if label:
            result[cluster_id] = LabelInfo(title=label.title, description=label.description)
        else:
            result[cluster_id] = None

    return result


def execute_set_cluster_label(
    state: ClusterLabelingState, cluster_id: int, title: str, description: str
) -> tuple[ClusterLabel, str]:
    """Execute set_cluster_label tool with state.

    Returns the new label and a confirmation message.
    The tools node should update state["current_labels"][cluster_id] with the returned label.
    """
    new_label = ClusterLabel(title=title, description=description)
    return new_label, f"Label set for cluster {cluster_id}: '{title}'"


def execute_bulk_set_labels(state: ClusterLabelingState, labels: list[dict]) -> tuple[dict[int, ClusterLabel], str]:
    """Execute bulk_set_labels tool with state.

    Returns a dict of new labels and a confirmation message.
    The tools node should update state["current_labels"] with all the returned labels.
    """
    new_labels: dict[int, ClusterLabel] = {}
    for entry in labels:
        cluster_id = entry["cluster_id"]
        new_labels[cluster_id] = ClusterLabel(title=entry["title"], description=entry["description"])

    return new_labels, f"Labels set for {len(new_labels)} clusters: {list(new_labels.keys())}"


def execute_finalize_labels(state: ClusterLabelingState) -> str:
    """Execute finalize_labels tool.

    Returns a message. The tools node should use this to trigger the finalize transition.
    """
    labeled_count = sum(1 for label in state["current_labels"].values() if label is not None)
    total_count = len(state["cluster_data"])
    return f"Finalized! {labeled_count}/{total_count} clusters labeled."


# List of all tool schemas for binding to the LLM
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


def execute_tool(tool_name: str, tool_args: dict[str, Any], state: ClusterLabelingState) -> Any:
    """Execute a tool by name with the given arguments and state.

    Returns the tool result.
    """
    if tool_name == "get_clusters_overview":
        return execute_get_clusters_overview(state)
    elif tool_name == "get_all_clusters_with_sample_titles":
        return execute_get_all_clusters_with_sample_titles(
            state, titles_per_cluster=tool_args.get("titles_per_cluster", 10)
        )
    elif tool_name == "get_cluster_trace_titles":
        return execute_get_cluster_trace_titles(
            state, cluster_id=tool_args["cluster_id"], limit=tool_args.get("limit", 30)
        )
    elif tool_name == "get_trace_details":
        return execute_get_trace_details(state, trace_ids=tool_args["trace_ids"])
    elif tool_name == "get_current_labels":
        return execute_get_current_labels(state)
    elif tool_name == "set_cluster_label":
        return execute_set_cluster_label(
            state,
            cluster_id=tool_args["cluster_id"],
            title=tool_args["title"],
            description=tool_args["description"],
        )
    elif tool_name == "bulk_set_labels":
        return execute_bulk_set_labels(state, labels=tool_args["labels"])
    elif tool_name == "finalize_labels":
        return execute_finalize_labels(state)
    else:
        raise ValueError(f"Unknown tool: {tool_name}")
