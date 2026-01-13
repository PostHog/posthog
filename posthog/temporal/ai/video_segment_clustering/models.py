"""Data models for video segment clustering workflow."""

from dataclasses import dataclass
from typing import TypedDict

from pydantic import BaseModel

from posthog.temporal.ai.video_segment_clustering.constants import DEFAULT_LOOKBACK_WINDOW, MIN_SEGMENTS_FOR_CLUSTERING


@dataclass
class CoordinatorInputs:
    """Input parameters for the coordinator workflow."""

    pass  # Uses feature flag to discover teams


@dataclass
class ClusteringWorkflowInputs:
    """Input parameters for the per-team clustering workflow."""

    team_id: int
    lookback_hours: int = int(DEFAULT_LOOKBACK_WINDOW.total_seconds() / 3600)
    min_segments: int = MIN_SEGMENTS_FOR_CLUSTERING


@dataclass
class VideoSegmentMetadata:
    """Lightweight video segment metadata (no embedding)."""

    document_id: str  # Format: "{session_id}:{start_time}:{end_time}"
    session_id: str
    start_time: str
    end_time: str
    distinct_id: str
    content: str
    timestamp: str  # ISO format


@dataclass
class VideoSegment:
    """A video segment from document_embeddings (with embedding for clustering)."""

    document_id: str  # Format: "{session_id}:{start_time}:{end_time}"
    session_id: str
    start_time: str
    end_time: str
    distinct_id: str
    content: str
    embedding: list[float]
    timestamp: str  # ISO format


@dataclass
class FetchSegmentsResult:
    """Result from fetching segments (lightweight, no embeddings)."""

    segments: list[VideoSegmentMetadata]
    latest_timestamp: str | None  # ISO format, for updating watermark


class ImpactFlags(TypedDict):
    """Impact flags for a segment derived from session data."""

    failure_detected: bool
    confusion_detected: bool
    abandonment_detected: bool


@dataclass
class SegmentWithImpact:
    """A segment with computed impact data (no embedding)."""

    segment: VideoSegmentMetadata
    impact_score: float
    impact_flags: ImpactFlags


@dataclass
class SegmentImpactData:
    """Lightweight segment impact data for labeling (no embeddings)."""

    document_id: str
    content: str
    distinct_id: str
    timestamp: str | None
    impact_score: float
    impact_flags: ImpactFlags


@dataclass
class ClusterContext:
    """Context data for a cluster passed to LLM for labeling/actionability."""

    segment_contents: list[str]
    segment_impact_flags: list[ImpactFlags]
    aggregate_impact_score: float
    distinct_user_count: int
    occurrence_count: int
    last_occurrence_iso: str | None


@dataclass
class Cluster:
    """A cluster of similar video segments."""

    cluster_id: int
    segment_ids: list[str]  # document_ids of segments in this cluster
    centroid: list[float]  # 3072-dim embedding centroid
    size: int


@dataclass
class ClusteringResult:
    """Result from HDBSCAN clustering."""

    clusters: list[Cluster]
    noise_segment_ids: list[str]  # Segments that didn't fit any cluster (label=-1)
    labels: list[int]  # Cluster assignment for each segment
    segment_to_cluster: dict[str, int]  # document_id -> cluster_id


@dataclass
class TaskMatch:
    """A match between a cluster and an existing Task."""

    cluster_id: int
    task_id: str
    distance: float


@dataclass
class MatchingResult:
    """Result from matching clusters to existing Tasks."""

    new_clusters: list[Cluster]  # Clusters that need new Tasks
    matched_clusters: list[TaskMatch]  # Clusters matched to existing Tasks


class ClusterLabel(BaseModel):
    """LLM-generated label for a cluster."""

    actionable: bool
    title: str = ""
    description: str = ""


@dataclass
class LabelingResult:
    """Result from LLM labeling."""

    labels: dict[int, ClusterLabel]  # cluster_id -> label


@dataclass
class TaskCreationResult:
    """Result from creating/updating Tasks."""

    tasks_created: int
    tasks_updated: int
    task_ids: list[str]


@dataclass
class LinkingResult:
    """Result from linking segments to Tasks."""

    links_created: int
    watermark_updated: bool


@dataclass
class WorkflowResult:
    """Final result of the clustering workflow."""

    team_id: int
    segments_processed: int
    clusters_found: int
    tasks_created: int
    tasks_updated: int
    links_created: int
    success: bool
    error: str | None = None


# Activity input/output types


@dataclass
class FetchSegmentsActivityInputs:
    """Input for fetch segments activity."""

    team_id: int
    since_timestamp: str | None  # ISO format, None = use clustering state
    lookback_hours: int


@dataclass
class ClusterSegmentsActivityInputs:
    """Input for cluster segments activity."""

    team_id: int
    document_ids: list[str]


@dataclass
class CreateHighImpactClustersActivityInputs:
    """Input for creating single-segment clusters for high-impact noise segments."""

    team_id: int
    document_ids: list[str]
    starting_cluster_id: int


@dataclass
class MatchClustersActivityInputs:
    """Input for match clusters activity."""

    team_id: int
    clusters: list[Cluster]


@dataclass
class ClusterForLabeling:
    """Lightweight cluster for labeling (no centroid embedding)."""

    cluster_id: int
    segment_ids: list[str]


@dataclass
class GenerateLabelsActivityInputs:
    """Input for generate labels activity."""

    team_id: int
    clusters: list[ClusterForLabeling]
    segment_impact_data: list[SegmentImpactData]


@dataclass
class CreateUpdateTasksActivityInputs:
    """Input for create/update tasks activity."""

    team_id: int
    new_clusters: list[Cluster]
    matched_clusters: list[TaskMatch]
    labels: dict[int, ClusterLabel]
    segments_with_impact: list[SegmentWithImpact]


@dataclass
class LinkSegmentsActivityInputs:
    """Input for link segments activity."""

    team_id: int
    task_ids: list[str]  # All task IDs (new and existing)
    segments_with_impact: list[SegmentWithImpact]
    segment_to_cluster: dict[str, int]
    cluster_to_task: dict[int, str]  # cluster_id -> task_id
    latest_timestamp: str | None


@dataclass
class FetchRecentSessionsActivityInputs:
    """Input for fetching recent sessions for summarization priming."""

    team_id: int
    lookback_hours: int


@dataclass
class FetchRecentSessionsResult:
    """Result from fetching recent sessions."""

    session_ids: list[str]


@dataclass
class SummarizeSessionsActivityInputs:
    """Input for summarizing sessions activity."""

    team_id: int
    session_ids: list[str]


@dataclass
class SummarizeSessionsResult:
    """Result from summarizing sessions."""

    sessions_summarized: int
    sessions_failed: int
    sessions_skipped: int
