import dataclasses
from enum import Enum
from typing import Literal

from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs

from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext


class SessionSummaryStreamUpdate(Enum):
    """Types of updates that can be streamed during session group summarization."""

    UI_STATUS = "ui_status"  # Status messages for UI progress display
    FINAL_RESULT = "final_result"  # Final summarization result


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryInputs:
    """Workflow input to get summary for a group of sessions"""

    session_ids: list[str]
    user_id: int
    user_distinct_id_to_log: str | None = None
    team_id: int
    redis_key_base: str
    summary_title: str | None
    # Timestamps required to avoid reading too many days from ClickHouse
    min_timestamp_str: str
    max_timestamp_str: str
    model_to_use: str
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False
    video_validation_enabled: bool | Literal["full"] | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionBatchFetchOutput:
    """Result of fetching session batch data, tracking both successful and expected skips."""

    fetched_session_ids: list[str]
    # Sessions skipped due to known unsummarizable conditions (too short, no events after filtering)
    expected_skip_session_ids: list[str]


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryOfSummariesInputs:
    """Base input for group summary activities"""

    single_session_summaries_inputs: list[SingleSessionSummaryInputs]
    user_id: int
    user_distinct_id_to_log: str | None = None
    team_id: int
    summary_title: str | None
    redis_key_base: str
    model_to_use: str
    extra_summary_context: ExtraSummaryContext | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryPatternsExtractionChunksInputs:
    """Input from patterns extraction activity to activity combining patterns from different sessions chunks"""

    redis_keys_of_chunks_to_combine: list[str]
    session_ids: list[str]
    user_id: int
    user_distinct_id_to_log: str | None = None
    team_id: int
    redis_key_base: str
    extra_summary_context: ExtraSummaryContext | None = None
