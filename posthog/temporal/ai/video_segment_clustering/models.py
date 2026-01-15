"""Data models for video segment clustering."""

from dataclasses import dataclass

from pydantic import BaseModel

from posthog.temporal.ai.video_segment_clustering.constants import DEFAULT_LOOKBACK_WINDOW, MIN_SEGMENTS_FOR_CLUSTERING


@dataclass
class ClusteringWorkflowInputs:
    team_id: int
    lookback_hours: int = int(DEFAULT_LOOKBACK_WINDOW.total_seconds() / 3600)
    min_segments: int = MIN_SEGMENTS_FOR_CLUSTERING


@dataclass
class VideoSegmentMetadata:
    document_id: str  # Format: "{session_id}:{start_time}:{end_time}"
    session_id: str
    start_time: str
    end_time: str
    distinct_id: str
    content: str
    timestamp: str  # ISO format


@dataclass
class VideoSegment:
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
    segments: list[VideoSegmentMetadata]
    latest_timestamp: str | None  # ISO format, for updating watermark


@dataclass
class ClusterContext:
    """Context data for a cluster passed to LLM for labeling/actionability."""

    segment_contents: list[str]
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
    tasks_created: int
    tasks_updated: int
    task_ids: list[str]


@dataclass
class LinkingResult:
    links_created: int
    watermark_updated: bool


@dataclass
class WorkflowResult:
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
    team_id: int
    since_timestamp: str | None  # ISO format, None = use clustering state
    lookback_hours: int


@dataclass
class ClusterSegmentsActivityInputs:
    team_id: int
    document_ids: list[str]
    create_single_segment_clusters_for_noise: bool = True


@dataclass
class CreateNoiseClustersActivityInputs:
    team_id: int
    document_ids: list[str]
    starting_cluster_id: int


@dataclass
class MatchClustersActivityInputs:
    team_id: int
    clusters: list[Cluster]


@dataclass
class ClusterForLabeling:
    """Lightweight cluster for labeling (no centroid embedding)."""

    cluster_id: int
    segment_ids: list[str]


@dataclass
class GenerateLabelsActivityInputs:
    team_id: int
    clusters: list[ClusterForLabeling]
    segments: list[VideoSegmentMetadata]


@dataclass
class CreateUpdateTasksActivityInputs:
    team_id: int
    new_clusters: list[Cluster]
    matched_clusters: list[TaskMatch]
    labels: dict[int, ClusterLabel]
    segments: list[VideoSegmentMetadata]


@dataclass
class LinkSegmentsActivityInputs:
    team_id: int
    task_ids: list[str]  # All task IDs (new and existing)
    segments: list[VideoSegmentMetadata]
    segment_to_cluster: dict[str, int]
    cluster_to_task: dict[int, str]  # cluster_id -> task_id
    latest_timestamp: str | None


@dataclass
class FetchRecentSessionsActivityInputs:
    team_id: int
    lookback_hours: int


@dataclass
class FetchRecentSessionsResult:
    session_ids: list[str]


@dataclass
class SummarizeSessionsActivityInputs:
    team_id: int
    session_ids: list[str]


@dataclass
class SummarizeSessionsResult:
    sessions_summarized: int
    sessions_failed: int
    sessions_skipped: int


@dataclass
class PrimeSessionEmbeddingsActivityInputs:
    team_id: int
    lookback_hours: int


@dataclass
class PrimeSessionEmbeddingsResult:
    session_ids_found: int
    sessions_summarized: int
    sessions_skipped: int
    sessions_failed: int


@dataclass
class PersistTasksActivityInputs:
    team_id: int
    new_clusters: list[Cluster]
    matched_clusters: list[TaskMatch]
    labels: dict[int, ClusterLabel]
    segments: list[VideoSegmentMetadata]
    segment_to_cluster: dict[str, int]
    latest_timestamp: str | None


@dataclass
class PersistTasksResult:
    tasks_created: int
    tasks_updated: int
    task_ids: list[str]
    links_created: int
    watermark_updated: bool
