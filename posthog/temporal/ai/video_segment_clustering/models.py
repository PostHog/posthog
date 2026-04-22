"""Data models for session video summary priming workflows (legacy package path: video_segment_clustering)."""

from dataclasses import dataclass

from posthog.temporal.ai.video_segment_clustering.constants import DEFAULT_LOOKBACK_WINDOW


@dataclass
class ClusteringWorkflowInputs:
    team_id: int
    lookback_hours: int = int(DEFAULT_LOOKBACK_WINDOW.total_seconds() / 3600)
    min_segments: int = 0  # Deprecated
    skip_priming: bool = False


@dataclass
class PrimeSessionEmbeddingsActivityInputs:
    team_id: int
    lookback_hours: int


@dataclass
class GetSessionsToPrimeResult:
    """Sessions that still need a video-based summary (embedding priming), plus a user to run workflows as."""

    session_ids_to_summarize: list[str]
    user_id: int | None
    user_distinct_id: str | None
