import dataclasses

from products.enterprise.backend.hogai.session_summaries.session.summarize_session import ExtraSummaryContext


@dataclasses.dataclass(frozen=True, kw_only=True)
class SingleSessionSummaryInputs:
    """Workflow input to get summary for a single session"""

    session_id: str
    user_id: int
    team_id: int
    redis_key_base: str
    model_to_use: str
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False
    video_validation_enabled: bool | None = None
