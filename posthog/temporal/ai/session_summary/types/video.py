from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext


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


class UploadedVideo(BaseModel):
    """Reference to a video uploaded to Gemini for analysis"""

    model_config = ConfigDict(frozen=True)

    file_uri: str
    mime_type: str
    duration: int = Field(description="Duration in seconds")


class UploadVideoToGeminiOutput(TypedDict):
    """Return type for upload_video_to_gemini_activity including uploaded video and team name"""

    uploaded_video: UploadedVideo
    team_name: str


class VideoSegmentSpec(BaseModel):
    """Specification for a segment of video to analyze"""

    model_config = ConfigDict(frozen=True)

    segment_index: int
    start_time: float = Field(description="Seconds from start of video")
    end_time: float = Field(description="Seconds from start of video")

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")
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


class ConsolidatedVideoAnalysis(BaseModel):
    """Complete output from video segment consolidation including segments, outcomes, and session-level analysis."""

    model_config = ConfigDict(frozen=True)

    segments: list[ConsolidatedVideoSegment]
    session_outcome: VideoSessionOutcome
    segment_outcomes: list[VideoSegmentOutcome]
