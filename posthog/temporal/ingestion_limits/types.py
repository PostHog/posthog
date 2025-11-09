from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from posthog.kafka_client.topics import KAFKA_INGESTION_WARNINGS


class ReportDestination(str, Enum):
    SLACK = "slack"
    KAFKA = "kafka"
    BOTH = "both"


class Classification(str, Enum):
    UUID = "uuid"
    EMAIL = "email"
    AMBIGUOUS = "ambiguous"


class HighVolumeDistinctId(BaseModel):
    team_id: int
    distinct_id: str
    offending_event_count: int
    classification: Classification


class IngestionLimitsWorkflowInput(BaseModel):
    report_destination: ReportDestination = ReportDestination.KAFKA
    slack_channel: Optional[str] = "#alerts-ingestion"
    kafka_topic: Optional[str] = KAFKA_INGESTION_WARNINGS
    time_window_minutes: int = 10
    known_distinct_id_threshold: int = 20000
    ambiguous_distinct_id_threshold: int = 10000


class IngestionLimitsReport(BaseModel):
    high_volume_distinct_ids: list[HighVolumeDistinctId]
    total_candidates: int
    timestamp: datetime
    known_distinct_id_threshold: int
    ambiguous_distinct_id_threshold: int
    time_window_minutes: int


class ReportIngestionLimitsInput(BaseModel):
    workflow_inputs: IngestionLimitsWorkflowInput
    report: IngestionLimitsReport
