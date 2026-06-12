"""Dataclass inputs/outputs for evaluation reports activities."""

import dataclasses
from typing import Any


@dataclasses.dataclass
class ScheduleAllEvalReportsWorkflowInputs:
    buffer_minutes: int = 15


@dataclasses.dataclass
class CheckCountTriggeredReportsWorkflowInputs:
    pass


@dataclasses.dataclass
class FetchDueEvalReportsOutput:
    report_ids: list[str]


@dataclasses.dataclass
class PrepareReportContextInput:
    report_id: str
    manual: bool = False


@dataclasses.dataclass
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


@dataclasses.dataclass
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


@dataclasses.dataclass
class GenerateAndDeliverEvalReportWorkflowInput:
    report_id: str
    manual: bool = False
