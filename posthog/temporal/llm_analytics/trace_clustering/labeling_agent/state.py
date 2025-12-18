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

    Used with create_react_agent. The messages field uses add_messages reducer
    for proper message history management.
    """

    # LangGraph message history (required by create_react_agent)
    messages: Annotated[list, add_messages]

    # Input data (set at start, read by tools via InjectedState)
    team_id: int
    cluster_data: dict[int, ClusterTraceData]  # cluster_id -> cluster info with traces
    all_trace_summaries: dict[str, TraceSummary]  # trace_id -> full summary

    # Working state (mutated by tools via InjectedState)
    current_labels: dict[int, ClusterLabel | None]  # cluster_id -> label or None


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
