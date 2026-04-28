import dataclasses
from typing import TypedDict

from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext


@dataclasses.dataclass(frozen=True, kw_only=True)
class SingleSessionSummaryInputs:
    """Workflow input to get summary for a single session"""

    session_id: str
    user_id: int
    user_distinct_id_to_log: str | None = None
    team_id: int
    redis_key_base: str
    model_to_use: str
    extra_summary_context: ExtraSummaryContext | None = None
    product_context: str | None = None
    local_reads_prod: bool = False
    video_based: bool = False
    trigger_session_id: str | None = None


class SingleSessionProgress(TypedDict):
    """Progress state exposed by SummarizeSingleSessionWorkflow via get_progress query.

    Populated only for the video-based flow.
    """

    phase: str
    step: int
    total_steps: int
    rasterizer_workflow_id: str | None
    segments_total: int
    segments_completed: int
