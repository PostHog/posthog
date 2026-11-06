"""What the investigated check measured, read from whichever stack recorded it.

The insight stack keeps it on an `AlertCheck`. The alerts platform never writes one, so an
investigation of a platform evaluation carries it on its `InsightAlertInvestigation` row.
"""

from __future__ import annotations

from typing import Any

from posthog.dataclasses import frozen

from products.alerts.backend.models.alert import AlertCheck
from products.alerts.backend.models.investigation import InsightAlertInvestigation


@frozen
class EvaluatedCheck:
    calculated_value: float | None
    interval: str | None
    triggered_dates: list[str]
    triggered_points: list[int]
    triggered_metadata: dict[str, Any]
    reference: str

    @classmethod
    def of_alert_check(cls, alert_check: AlertCheck) -> EvaluatedCheck:
        return cls(
            calculated_value=alert_check.calculated_value,
            interval=alert_check.interval,
            triggered_dates=list(alert_check.triggered_dates or []),
            triggered_points=list(alert_check.triggered_points or []),
            triggered_metadata=dict(alert_check.triggered_metadata or {}),
            reference=f"Alert check id {alert_check.id}",
        )

    @classmethod
    def of_investigation(cls, investigation: InsightAlertInvestigation) -> EvaluatedCheck:
        evaluated = investigation.evaluated or {}
        value = evaluated.get("value")
        return cls(
            calculated_value=float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
            interval=evaluated.get("interval"),
            triggered_dates=list(evaluated.get("triggered_dates") or []),
            triggered_points=list(evaluated.get("triggered_points") or []),
            triggered_metadata=dict(evaluated.get("triggered_metadata") or {}),
            reference=f"Investigation id {investigation.id}",
        )
