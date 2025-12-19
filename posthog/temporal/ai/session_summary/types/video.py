import dataclasses

from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext


@dataclasses.dataclass(frozen=True, kw_only=True)
class VideoSummarySingleSessionInputs:
    """Workflow input for video-based session analysis"""

    session_id: str
    user_id: int
    user_distinct_id_to_log: str | None = None
    team_id: int
    redis_key_base: str
    model_to_use: str
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False


@dataclasses.dataclass(frozen=True)
class UploadedVideo:
    """Reference to a video uploaded to Gemini for analysis"""

    file_uri: str
    mime_type: str
    duration: float  # Duration in seconds


@dataclasses.dataclass(frozen=True)
class VideoSegmentSpec:
    """Specification for a segment of video to analyze"""

    segment_index: int
    start_time: float  # Seconds from start of video
    end_time: float  # Seconds from start of video


@dataclasses.dataclass(frozen=True)
class VideoSegmentOutput:
    """Output representing a segment from video analysis

    Contains detailed description of what happened during this time segment.
    """

    start_time: str  # Format: MM:SS or HH:MM:SS
    end_time: str  # Format: MM:SS or HH:MM:SS
    description: str


@dataclasses.dataclass(frozen=True)
class ConsolidatedVideoSegment:
    """A semantically meaningful segment consolidated from raw video analysis outputs.

    Unlike VideoSegmentOutput which has generic titles, this has a meaningful title
    created by LLM analysis of the segment descriptions.
    """

    title: str  # Meaningful segment title (e.g., "User onboarding flow", "Debugging API errors")
    start_time: str  # Format: MM:SS or HH:MM:SS
    end_time: str  # Format: MM:SS or HH:MM:SS
    description: str  # Combined/refined description of what happened
