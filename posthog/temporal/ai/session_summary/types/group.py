import dataclasses

from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs


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
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False


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
    redis_key_base: str
    extra_summary_context: ExtraSummaryContext | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryPatternsExtractionChunksInputs:
    """Input from patterns extraction activity to activity combining patterns from different sessions chunks"""

    redis_keys_of_chunks_to_combine: list[str]
    session_ids: list[str]
    user_id: int
    redis_key_base: str
    extra_summary_context: ExtraSummaryContext | None = None
