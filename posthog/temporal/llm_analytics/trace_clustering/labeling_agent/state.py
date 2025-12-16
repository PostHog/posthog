"""State definitions for the cluster labeling agent."""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel, TraceSummary


class TraceMetadata(TypedDict):
    """Metadata for a trace within a cluster."""

    trace_id: str
    title: str
    rank: int
    distance_to_centroid: float
    x: float
    y: float


class ClusterTraceData(TypedDict):
    """All trace data for a cluster."""

    cluster_id: int
    size: int
    centroid_x: float
    centroid_y: float
    traces: dict[str, TraceMetadata]  # trace_id -> metadata


class ClusterLabelingState(TypedDict):
    """State for the cluster labeling agent graph.

    This state is passed through the LangGraph and updated by nodes.
    """

    # Input data (set at start, immutable during run)
    team_id: int
    cluster_data: dict[int, ClusterTraceData]  # cluster_id -> cluster info with traces
    all_trace_summaries: dict[str, TraceSummary]  # trace_id -> full summary

    # Working state (mutated by agent via tools)
    current_labels: dict[int, ClusterLabel | None]  # cluster_id -> label or None

    # LangGraph message history
    messages: Annotated[list, add_messages]

    # Control flow
    iterations: int
    max_iterations: int


class ClusterOverview(TypedDict):
    """Overview of a cluster returned by get_clusters_overview tool."""

    cluster_id: int
    size: int
    centroid_x: float
    centroid_y: float


class TraceTitleInfo(TypedDict):
    """Trace title info returned by get_cluster_trace_titles tool."""

    trace_id: str
    title: str
    rank: int
    distance_to_centroid: float
    x: float
    y: float


class TraceDetail(TypedDict):
    """Full trace detail returned by get_trace_details tool."""

    trace_id: str
    title: str
    flow_diagram: str
    bullets: str
    interesting_notes: str


class LabelInfo(TypedDict):
    """Label info returned by get_current_labels tool."""

    title: str
    description: str


class ClusterWithSampleTitles(TypedDict):
    """Cluster info with sample trace titles returned by get_all_clusters_with_sample_titles."""

    cluster_id: int
    size: int
    sample_titles: list[str]  # Just the titles, sorted by distance to centroid
