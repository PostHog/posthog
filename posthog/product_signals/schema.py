from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Optional

import structlog

from posthog.api.capture import capture_internal

logger = structlog.get_logger(__name__)


class ProductSignalSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProductSignalType(StrEnum):
    NEW_ISSUE = "new_issue"
    FUNNEL_ANOMOLY = "funnel_anomoly"


class ProductSignalSource(StrEnum):
    ERROR_TRACKING = "error_tracking"
    PRODUCT_ANALYTICS = "product_analytics"


class ProductSignalException(Exception):
    def __init__(self, signal: "ProductSignal") -> None:
        super().__init__(
            f"ProductSignalException: {signal.signal_type.value} [{signal.severity.value}] - {signal.title}"
        )
        self.signal_type = signal.signal_type
        self.severity = signal.severity
        self.title = signal.title
        self.description = signal.description
        self.source = signal.source
        self.distinct_id = signal.distinct_id
        self.metadata = signal.metadata
        self.timestamp = signal.timestamp


@dataclass
class ProductSignal:
    signal_type: ProductSignalType
    severity: ProductSignalSeverity
    title: str
    source: ProductSignalSource
    distinct_id: str
    description: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[datetime] = None

    def to_event_properties(self) -> dict[str, Any]:
        props = {
            **self.metadata,
            "$product_signal_type": self.signal_type.value,
            "$product_signal_severity": self.severity.value,
            "$product_signal_title": self.title,
            "$product_signal_source": self.source.value,
        }

        if self.description:
            props["$product_signal_description"] = self.description

        return props

    @staticmethod
    def create(
        team_token: str,
        signal: "ProductSignal",
        distinct_id: str,
    ) -> None:
        timestamp = signal.timestamp or datetime.now()

        try:
            capture_internal(
                token=team_token,
                event_name="$product_signal",
                event_source="product_signals",
                timestamp=timestamp,
                distinct_id=distinct_id,
                properties=signal.to_event_properties(),
                process_person_profile=False,
            )
        except Exception as e:
            raise ProductSignalException(signal) from e
