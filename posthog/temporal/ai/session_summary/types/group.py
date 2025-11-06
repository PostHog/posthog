import dataclasses
from enum import Enum

from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs

from products.enterprise.backend.hogai.session_summaries.session.summarize_session import ExtraSummaryContext


class SessionSummaryStreamUpdate(Enum):
    """Types of updates that can be streamed during session group summarization."""

    UI_STATUS = "ui_status"  # Status messages for UI progress display
    NOTEBOOK_UPDATE = "notebook_update"  # Intermediate state for notebook display
    FINAL_RESULT = "final_result"  # Final summarization result


class SessionSummaryStep(Enum):
    """Steps in the session group summarization process."""

    WATCHING_SESSIONS = "watching_sessions"
    FINDING_PATTERNS = "finding_patterns"
    GENERATING_REPORT = "generating_report"


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryInputs:
    """Workflow input to get summary for a group of sessions"""

    session_ids: list[str]
    user_id: int
    team_id: int
    redis_key_base: str
    # Timestamps required to avoid reading too many days from ClickHouse
    min_timestamp_str: str
    max_timestamp_str: str
    model_to_use: str
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False
    video_validation_enabled: bool | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummarySingleSessionOutput:
    """Output after generating a single session summary to pass through to the next group summary activity"""

    session_summary_str: str
    redis_input_key: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryOfSummariesInputs:
    """Base input for group summary activities"""

    single_session_summaries_inputs: list[SingleSessionSummaryInputs]
    user_id: int
    team_id: int
    redis_key_base: str
    model_to_use: str
    extra_summary_context: ExtraSummaryContext | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryPatternsExtractionChunksInputs:
    """Input from patterns extraction activity to activity combining patterns from different sessions chunks"""

    redis_keys_of_chunks_to_combine: list[str]
    session_ids: list[str]
    user_id: int
    team_id: int
    redis_key_base: str
    extra_summary_context: ExtraSummaryContext | None = None
