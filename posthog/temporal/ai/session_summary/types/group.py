import dataclasses

from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryInputs:
    """Workflow input to get summary for a group of sessions"""

    session_ids: list[str]
    user_id: int
    team_id: int
    redis_key_base: str
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummarySingleSessionOutput:
    """Output after generating a single session summary to pass through to the next group summary activity"""

    session_summary_str: str
    redis_input_key: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class SessionGroupSummaryOfSummariesInputs:
    single_session_summaries_inputs: list[SingleSessionSummaryInputs]
    user_id: int
    redis_key_base: str
    extra_summary_context: ExtraSummaryContext | None = None
