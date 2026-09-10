"""Dataclass inputs/outputs for evaluation reports activities."""

import dataclasses
from typing import Any

from posthog.dataclasses import frozen

DEFAULT_MAX_SCHEDULED_EVAL_REPORTS_PER_RUN = 300
MAX_SCHEDULED_EVAL_REPORTS_PER_RUN = 1_000

# The count-triggered coordinator currently checks roughly 1,070 US reports every five
# minutes. Two thousand keeps almost 2x production headroom while the 5,000 hard ceiling
# and the wire-size guard prevent an operator override from creating an oversized activation.
DEFAULT_MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN = 2_000
MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN = 5_000


@dataclasses.dataclass
class ScheduleAllEvalReportsWorkflowInputs:
    buffer_minutes: int = 15
    max_reports_per_run: int = DEFAULT_MAX_SCHEDULED_EVAL_REPORTS_PER_RUN
    region: str = "local"


@dataclasses.dataclass
class CheckCountTriggeredReportsWorkflowInputs:
    max_reports_per_run: int = DEFAULT_MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN
    region: str = "local"


@dataclasses.dataclass
class CheckCountTriggeredEvalReportInput:
    report_id: str


@dataclasses.dataclass
class CheckCountTriggeredEvalReportOutput:
    report_id: str
    due: bool
    skipped_reason: str | None = None


@dataclasses.dataclass
class CheckCountTriggeredEvalReportsBatchInput:
    report_ids: list[str]


@dataclasses.dataclass
class CheckCountTriggeredEvalReportsBatchOutput:
    results: list[CheckCountTriggeredEvalReportOutput]


@dataclasses.dataclass
class FetchDueEvalReportsOutput:
    report_ids: list[str]
    # Count-triggered candidates grouped one team per group, each group at most
    # COUNT_TRIGGER_QUERY_WIDTH wide. None when emitted by a pre-batching worker;
    # the workflow then keeps the legacy per-report path.
    report_id_groups: list[list[str]] | None = None
    due_items_lower_bound: int = 0
    oldest_due_at_iso: str | None = None
    payload_bytes: int = 0
    limited_by: str = "none"


@dataclasses.dataclass
class PrepareReportContextInput:
    report_id: str
    manual: bool = False


@frozen
class PrepareReportContextOutput:
    report_id: str
    team_id: int
    evaluation_id: str
    evaluation_name: str
    evaluation_description: str
    evaluation_prompt: str
    evaluation_type: str
    period_start: str
    period_end: str
    previous_period_start: str
    report_prompt_guidance: str = ""
    output_type: str = "boolean"
    true_is_failure: bool = False


@frozen
class RunEvalReportAgentInput:
    report_id: str
    team_id: int
    evaluation_id: str
    evaluation_name: str
    evaluation_description: str
    evaluation_prompt: str
    evaluation_type: str
    period_start: str
    period_end: str
    previous_period_start: str
    report_prompt_guidance: str = ""
    output_type: str = "boolean"
    true_is_failure: bool = False
    trace_id: str = ""
    session_id: str = ""


@dataclasses.dataclass
class RunEvalReportAgentOutput:
    """Output of the eval report agent activity.

    `content` is a serialized `EvalReportContent` dict (includes title, sections,
    citations, metrics — no separate metadata field).
    """

    report_id: str
    content: dict[str, Any]
    period_start: str
    period_end: str
    generation_status: str = "completed"


@dataclasses.dataclass
class StoreReportRunInput:
    report_id: str
    team_id: int
    evaluation_id: str
    content: dict[str, Any]
    period_start: str
    period_end: str


@dataclasses.dataclass
class StoreReportRunOutput:
    report_run_id: str


@dataclasses.dataclass
class DeliverReportInput:
    report_id: str
    report_run_id: str


@dataclasses.dataclass
class UpdateNextDeliveryDateInput:
    report_id: str
    period_end: str
    generation_status: str = "completed"
    record_attempt: bool = True
    advance_data_cursor: bool | None = None


@dataclasses.dataclass
class GenerateAndDeliverEvalReportWorkflowInput:
    report_id: str
    manual: bool = False
