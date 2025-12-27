import dataclasses
from enum import Enum
from typing import Literal

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


@dataclasses.dataclass(frozen=True)
class UploadedVideo:
    """Reference to a video uploaded to Gemini for analysis"""

    file_uri: str
    mime_type: str
    duration: int  # Duration in seconds


@dataclasses.dataclass(frozen=True)
class VideoSegmentSpec:
    """Specification for a segment of video to analyze"""

    segment_index: int
    start_time: float  # Seconds from start of video
    end_time: float  # Seconds from start of video


# Using Enum to check the output values of LLM, but don't force the values (use `custom` if validation fails)
class VideoSegmentTypesEnum(Enum):
    PAGE_TITLE = "page_title"
    BLOCK_TITLE = "block_title"
    LABEL = "label"
    INPUT = "input"
    BUTTON = "button"
    LINK = "link"
    TAB = "tab"
    DROPDOWN = "dropdown"
    CHECKBOX = "checkbox"
    MODAL = "modal"
    DATETIME = "datetime"
    # Adding custom to allow LLM to add elements we didn't think about, to track later
    CUSTOM = "custom"

    def __repr__(self) -> str:
        return self.value


# Using Enum to check the output values of LLM, but don't force the values (use `custom` if validation fails)
class VideoSegmentInteractionsEnum(Enum):
    NAVIGATION = "navigation"
    SCROLL = "scroll"
    LOADING = "loading"
    STATIC = "static"
    HOVER = "hover"
    CLICK = "click"
    RESIZE = "resize"
    INPUT = "input"
    MEDIA = "media"
    # Adding custom to allow LLM to add interactions we didn't think about, to track later
    CUSTOM = "custom"

    def __repr__(self) -> str:
        return self.value


@dataclasses.dataclass(frozen=True)
class VideoSegmentElement:
    element_type: str
    element_value: str


@dataclasses.dataclass(frozen=True)
class VideoSegmentInteraction:
    interaction_source: Literal["video", "events"]
    interaction_type: str | None = None
    elements: list[VideoSegmentElement] | None = None
    # Timestamp of the start of the interaction, in real seconds (based on the metadata, not video),
    # to be able to link interactions to the session timeline
    s_from_start: int | None = None


@dataclasses.dataclass  # Not frozen, as we plan to extend it
class VideoSegmentOutput:
    """Output representing a segment from video analysis

    Contains detailed description of what happened during this time segment.
    """

    start_time: str  # Format: MM:SS or HH:MM:SS
    end_time: str  # Format: MM:SS or HH:MM:SS
    description: str
    interactions: list[VideoSegmentInteraction] | None = None
    timestamp_indicator: int | None = None


@dataclasses.dataclass(frozen=True)
class ConsolidatedVideoSegment:
    """A semantically meaningful segment consolidated from raw video analysis outputs.

    Unlike VideoSegmentOutput which is purely based on a timestamp range, ConsolidatedVideoSegment is a meaningful
    unit of something the user did/experienced.
    """

    title: str  # Meaningful segment title (e.g., "User onboarding flow", "Debugging API errors")
    start_time: str  # Format: MM:SS or HH:MM:SS
    end_time: str  # Format: MM:SS or HH:MM:SS
    description: str  # Combined/refined description of what happened
    # Success/failure indicators detected from video analysis
    success: bool = True  # Whether the segment appears successful
    failure_detected: bool = False  # User encountered errors/failures
    confusion_detected: bool = False  # User appeared confused (backtracking, hesitation)
    abandonment_detected: bool = False  # User abandoned a flow


@dataclasses.dataclass(frozen=True)
class VideoSessionOutcome:
    """Overall session outcome determined from video analysis."""

    success: bool
    description: str


@dataclasses.dataclass(frozen=True)
class ConsolidatedVideoAnalysis:
    """Complete output from video segment consolidation including segments, outcomes, and session-level analysis."""

    segments: list[ConsolidatedVideoSegment]
    session_outcome: VideoSessionOutcome
    segment_outcomes: list[dict]  # [{segment_index: int, success: bool, summary: str}]
