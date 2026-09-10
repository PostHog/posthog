"""Dataclass inputs/outputs for evaluation reports activities."""

import dataclasses
from typing import Any

from posthog.dataclasses import frozen

DEFAULT_MAX_SCHEDULED_EVAL_REPORTS_PER_RUN = 300
MAX_SCHEDULED_EVAL_REPORTS_PER_RUN = 1_000

# Count-triggered discovery checks the full eligible inventory on every poll, so the default
# page holds the current production inventory with headroom. Keep both bounds below Temporal's
# 2,000 pending-child default so an operator override cannot make one coordinator exceed it.
# The sizing evidence is in docs/superpowers/specs/2026-09-10-temporal-scheduler-resilience-design.md.
DEFAULT_MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN = 1_500
MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN = 1_500


@dataclasses.dataclass(frozen=True)
class ScheduleAllEvalReportsWorkflowInputs:
    buffer_minutes: int = 15
    max_reports_per_run: int = DEFAULT_MAX_SCHEDULED_EVAL_REPORTS_PER_RUN
    region: str = "local"


@dataclasses.dataclass(frozen=True)
class CheckCountTriggeredReportsWorkflowInputs:
    max_reports_per_run: int = DEFAULT_MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN
    region: str = "local"


@dataclasses.dataclass(frozen=True)
class AckEvalReportCursorsInput:
    trigger_type: str
    region: str
    cursor_before: str
    report_ids: list[str]


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


@dataclasses.dataclass(frozen=True)
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
    # None preserves replay for fetch results written before cursor acknowledgement moved into
    # its own activity. An empty string is a valid first-page cursor.
    cursor_before: str | None = None


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
