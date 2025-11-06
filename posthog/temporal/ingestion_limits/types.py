from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ReportDestination(str, Enum):
    SLACK = "slack"
    KAFKA = "kafka"
    BOTH = "both"


class HighVolumeDistinctId(BaseModel):
    team_id: int
    distinct_id: str
    offending_event_count: int


class IngestionLimitsWorkflowInput(BaseModel):
    report_destination: ReportDestination = ReportDestination.KAFKA
    slack_channel: Optional[str] = "#alerts-ingestion"
    kafka_topic: Optional[str] = None
    time_window_minutes: int = 10
    event_threshold: int = 10000


class IngestionLimitsReport(BaseModel):
    high_volume_distinct_ids: list[HighVolumeDistinctId]
    total_candidates: int
    timestamp: datetime
    event_threshold: int
    time_window_minutes: int


class ReportIngestionLimitsInput(BaseModel):
    workflow_inputs: IngestionLimitsWorkflowInput
    report: IngestionLimitsReport
