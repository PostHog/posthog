"""Data models for video segment clustering."""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from posthog.temporal.ai.video_segment_clustering.constants import DEFAULT_LOOKBACK_WINDOW, MIN_SEGMENTS_FOR_CLUSTERING


@dataclass
class ClusteringWorkflowInputs:
    team_id: int
    lookback_hours: int = int(DEFAULT_LOOKBACK_WINDOW.total_seconds() / 3600)
    min_segments: int = MIN_SEGMENTS_FOR_CLUSTERING
    skip_priming: bool = False


@dataclass
class VideoSegmentMetadata:
    document_id: str  # Format: "{session_id}:{start_time}:{end_time}"
    session_id: str
    start_time: str
    end_time: str
    session_start_time: str
    session_end_time: str
    session_duration: int
    session_active_seconds: int
    distinct_id: str
    content: str


@dataclass
class VideoSegment:
    document_id: str  # Format: "{session_id}:{start_time}:{end_time}"
    session_id: str
    start_time: str
    end_time: str
    session_start_time: str
    session_end_time: str
    session_duration: int
    session_active_seconds: int
    distinct_id: str
    content: str
    embedding: list[float]


@dataclass
class FetchSegmentsResult:
    segments: list[VideoSegmentMetadata]


@dataclass
class ClusterContext:
    """Context data for a cluster passed to LLM for labeling/actionability."""

    segment_contents: list[str]
    relevant_user_count: int
    occurrence_count: int
    last_occurrence_iso: str | None


@dataclass
class Cluster:
    """A cluster of similar video segments."""

    cluster_id: int
    segment_ids: list[str]  # document_ids of segments in this cluster
    size: int


@dataclass
class ClusteringResult:
    """Result from HDBSCAN clustering."""

    clusters: list[Cluster]
    noise_segment_ids: list[str]  # Segments that didn't fit any cluster (label=-1)
    labels: list[int]  # Cluster assignment for each segment
    segment_to_cluster: dict[str, int]  # document_id -> cluster_id


class ClusterLabel(BaseModel):
    """LLM-generated label for a cluster."""

    actionable: bool
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)


@dataclass
class LabelingResult:
    """Result from LLM labeling."""

    labels: dict[int, ClusterLabel]  # cluster_id -> label


@dataclass
class ClusterForLabeling:
    """Lightweight cluster for labeling (no centroid embedding)."""

    cluster_id: int
    segment_ids: list[str]


@dataclass
class EmitSignalsResult:
    signals_emitted: int
    clusters_skipped: int


# Activity input/output types


@dataclass
class FetchSegmentsActivityInputs:
    team_id: int
    lookback_hours: int


@dataclass
class ClusterSegmentsActivityInputs:
    team_id: int
    document_ids: list[str]


@dataclass
class CreateNoiseClustersActivityInputs:
    team_id: int
    document_ids: list[str]
    starting_cluster_id: int


@dataclass
class EmitSignalsActivityInputs:
    team_id: int
    clusters: list[Cluster]
    segments: list[VideoSegmentMetadata]
    segment_to_cluster: dict[str, int]  # document_id -> cluster_id
    workflow_run_id: str


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


@dataclass
class PrimeSessionEmbeddingsActivityInputs:
    team_id: int
    lookback_hours: int


@dataclass
class PrimeSessionEmbeddingsResult:
    session_ids_found: int
    sessions_summarized: int
    sessions_failed: int


@dataclass
class GetSessionsToPrimeResult:
    """Result from the activity that identifies sessions needing summarization."""

    session_ids_to_summarize: list[str]
    user_id: int | None
    user_distinct_id: str | None
