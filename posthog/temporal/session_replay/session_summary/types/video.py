from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from posthog.schema import ReplayInactivityPeriod

from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext

AI_TAGS_FIXED_TAXONOMY: dict[str, str] = {
    "onboarding": "First-time setup, account creation, getting-started flows",
    "error": "Visible errors, failed requests, broken UI — something went wrong",
    "frustration": "Rage clicks, repeated failures, visible confusion or backtracking",
    "idle": "Long pauses with no meaningful interaction",
    "navigation_only": "Browsing between pages without taking action",
    "search": "Searching or filtering to find specific content",
    "checkout": "Purchase or payment flows",
    "form_interaction": "Filling out forms, multi-step wizards, sign-ups",
    "account_management": "Profile, settings, preferences, subscriptions",
    "content_consumption": "Reading, watching, scrolling through content",
    "feature_exploration": "Trying out functionality, clicking around to learn what it does",
    "support": "Viewing help docs, contacting support, FAQ",
    "collaboration": "Sharing, commenting, inviting, reviewing others' work",
    "bot": "Behavior suggests an automated script or bot, not a real user",
}


class VideoSummarySingleSessionInputs(BaseModel):
    """Workflow input for video-based session analysis"""

    model_config = ConfigDict(frozen=True)

    session_id: str
    user_id: int
    user_distinct_id_to_log: str | None = None
    team_id: int
    redis_key_base: str
    model_to_use: str
    extra_summary_context: ExtraSummaryContext | None = None


class PrepSessionVideoAssetResult(BaseModel):
    """Result from preparing the session video ExportedAsset."""

    model_config = ConfigDict(frozen=True)

    asset_id: int
    needs_export: bool


class UploadedVideo(BaseModel):
    """Reference to a video uploaded to Gemini for analysis"""

    model_config = ConfigDict(frozen=True)

    file_uri: str
    gemini_file_name: str = Field(description="Gemini file identifier for deletion (e.g. 'files/abc123')")
    mime_type: str
    duration: int = Field(description="Duration in seconds")


class UploadVideoToGeminiOutput(TypedDict):
    """Return type for upload_video_to_gemini_activity including uploaded video and team name"""

    uploaded_video: UploadedVideo
    team_name: str
    # Stored as list of dicts from ReplayInactivityPeriod.model_dump()
    inactivity_periods: list[ReplayInactivityPeriod] | None


class VideoSegmentSpec(BaseModel):
    """Specification for a segment of video to analyze"""

    model_config = ConfigDict(frozen=True)

    segment_index: int
    start_time: float = Field(description="Seconds from start of session")
    end_time: float = Field(description="Seconds from start of session")
    recording_start_time: float = Field(description="Seconds from start of video")
    recording_end_time: float = Field(description="Seconds from start of video")

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")
        if self.recording_end_time <= self.recording_start_time:
            raise ValueError("recording_end_time must be greater than recording_start_time")
        return self


class VideoSegmentOutput(BaseModel):
    """Output representing a segment from video analysis

    Contains detailed description of what happened during this time segment.
    """

    model_config = ConfigDict(frozen=True)

    start_time: str = Field(description="Format: MM:SS or HH:MM:SS")
    end_time: str = Field(description="Format: MM:SS or HH:MM:SS")
    description: str


class ConsolidatedVideoSegment(BaseModel):
    """A semantically meaningful segment consolidated from raw video analysis outputs.

    Unlike VideoSegmentOutput which is purely based on a timestamp range, ConsolidatedVideoSegment is a meaningful
    unit of something the user did/experienced.
    """

    model_config = ConfigDict(frozen=True)

    title: str = Field(description="Meaningful segment title (e.g., 'User onboarding flow', 'Debugging API errors')")
    start_time: str = Field(description="Format: MM:SS or HH:MM:SS")
    end_time: str = Field(description="Format: MM:SS or HH:MM:SS")
    description: str = Field(description="Combined/refined description of what happened")
    success: bool = Field(default=True, description="Whether the segment appears successful")
    exception: Literal["blocking", "non-blocking"] | None = Field(
        default=None,
        description="Type of failure: 'blocking' if it stopped user progress, 'non-blocking' if user could continue",
    )
    confusion_detected: bool = Field(default=False, description="User appeared confused (backtracking, hesitation)")
    abandonment_detected: bool = Field(default=False, description="User abandoned a flow")


class VideoSessionOutcome(BaseModel):
    """Overall session outcome determined from video analysis."""

    model_config = ConfigDict(frozen=True)

    success: bool
    description: str


class VideoSegmentOutcome(BaseModel):
    """Outcome for a specific video segment."""

    model_config = ConfigDict(frozen=True)

    segment_index: int
    success: bool
    summary: str


class VideoFixSuggestion(BaseModel):
    """An actionable fix suggestion grounded in observed session behavior."""

    model_config = ConfigDict(frozen=True)

    segment_index: int = Field(description="Index of the segment where the issue was observed")
    issue: str = Field(description="What went wrong — specific error, failure, or friction point")
    evidence: str = Field(description="What was observed: exact error message, failed action, or user behavior")
    suggestion: str = Field(description="Actionable fix or improvement")


class SentimentSignal(BaseModel):
    """A specific observation that contributed to the session frustration score."""

    model_config = ConfigDict(frozen=True)

    signal_type: Literal[
        "rage_click",
        "repeated_error",
        "backtracking",
        "long_pause",
        "abandonment",
        "dead_click",
        "confusion_loop",
        "error_cascade",
        "other",
    ] = Field(description="Category of the observed frustration signal")
    segment_index: int = Field(description="Index of the segment where the signal was observed")
    description: str = Field(description="Brief description of the observed signal")
    intensity: float = Field(ge=0.0, le=1.0, description="How severe this signal is (0=mild, 1=extreme)")


class SessionSentiment(BaseModel):
    """Session-level sentiment scoring derived from video analysis."""

    model_config = ConfigDict(frozen=True)

    frustration_score: float = Field(
        ge=0.0, le=1.0, description="Overall frustration score (0.0=smooth session, 1.0=extremely frustrated)"
    )
    outcome: Literal["successful", "friction", "frustrated", "blocked"] = Field(
        description="How the session went: successful (no friction), friction (issues but recovered), frustrated (repeated issues, visible confusion), blocked (couldn't proceed)"
    )
    sentiment_signals: list[SentimentSignal] = Field(
        default_factory=list, description="Evidence signals backing the frustration score"
    )


class ConsolidatedVideoAnalysis(BaseModel):
    """Complete output from video segment consolidation including segments, outcomes, and session-level analysis."""

    model_config = ConfigDict(frozen=True)

    segments: list[ConsolidatedVideoSegment]
    session_outcome: VideoSessionOutcome
    segment_outcomes: list[VideoSegmentOutcome]
    fix_suggestions: list[VideoFixSuggestion] = Field(
        default_factory=list,
        description="Actionable fix suggestions grounded in observed issues — only include if there is clear evidence",
    )
    sentiment: SessionSentiment | None = Field(
        default=None, description="Session-level sentiment scoring with evidence signals"
    )


class SessionTaggingOutput(BaseModel):
    """Output from the session tagging LLM call."""

    model_config = ConfigDict(frozen=True)

    tags_fixed: list[str] = Field(description="1-5 tags from the fixed taxonomy")
    tags_freeform: list[str] = Field(description="1-5 specific free-form tags")
    highlighted: bool = Field(default=False, description="Whether the session is worth watching")


class ConsolidateVideoSegmentsOutput(TypedDict):
    """Return type for consolidate_video_segments_activity including analysis and tagging."""

    consolidated_analysis: ConsolidatedVideoAnalysis
    tagging: SessionTaggingOutput
