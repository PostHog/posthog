import dataclasses
from typing import Literal

from posthog.slo.types import SloConfig


# ─── Coordinator inputs ─────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class ScheduleAllAlertChecksWorkflowInputs:
    """Inputs for the scheduled coordinator workflow.

    No fields today; reserved for future tuning (per-tick batch size,
    alert kind filter). `frozen=True` is intentional and a deliberate
    improvement over ScheduleAllSubscriptionsWorkflowInputs — Temporal
    workflow inputs should be immutable.
    """


# ─── enumerate_due_alerts_activity I/O ──────────────────────────────
@dataclasses.dataclass(frozen=True)
class EnumerateDueAlertsActivityInputs:
    pass  # no inputs today; placeholder for future filtering


@dataclasses.dataclass(frozen=True)
class AlertInfo:
    """Minimal alert metadata needed to start a child workflow.

    Mirrors the tuple shape used today in check_alerts_task at
    posthog/tasks/alerts/checks.py:177-181.
    """

    alert_id: str
    team_id: int
    distinct_id: str
    calculation_interval: str | None
    insight_id: int


# ─── CheckAlertWorkflow inputs ──────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class CheckAlertWorkflowInputs:
    """Inputs for a single alert check workflow.

    Duplicates AlertInfo fields intentionally rather than nesting it:
    Temporal deserializes by the declared parameter type, so the SLO
    config must be on the type the workflow declares. Same pattern as
    TrackedSubscriptionInputs in posthog/temporal/subscriptions/types.py.

    `slo: SloConfig | None` is the field the SloInterceptor inspects
    (see posthog/temporal/common/slo_interceptor.py:20). When set, the
    interceptor emits slo_operation_started/_completed events around
    the entire workflow execution with replay protection.
    """

    alert_id: str
    team_id: int
    distinct_id: str
    calculation_interval: str | None
    insight_id: int
    slo: SloConfig | None = None


# ─── prepare_alert_activity I/O ─────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class PrepareAlertActivityInputs:
    alert_id: str


PrepareAction = Literal["evaluate", "skip", "auto_disable"]


@dataclasses.dataclass(frozen=True)
class PrepareAlertResult:
    """Routing instructions for the workflow after the prepare phase.

    `action`:
      - "evaluate":     proceed to phase 2
      - "skip":         exit cleanly (snoozed, weekend, quiet hours, deleted
                        insight, alert not found / not enabled, race window)
      - "auto_disable": validation failed; the activity has already disabled
                        the alert and persisted an errored AlertCheck row

    `reason`: human-readable, populated for "skip" and "auto_disable" for
              observability and SLO completion property tagging.
    """

    action: PrepareAction
    reason: str | None = None


# ─── evaluate_alert_activity I/O ────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class EvaluateAlertActivityInputs:
    alert_id: str


@dataclasses.dataclass(frozen=True)
class EvaluateAlertResult:
    """Result of the CH query + state machine + AlertCheck persistence.

    `alert_check_id`: row id of the just-created AlertCheck. The notify
                      activity reads this row by id to send the right
                      message and to mark targets_notified for idempotency.
    `should_notify`:  True iff state transitioned to FIRING / ERRORED, OR
                      we're sending a RESOLVED notification. Computed by
                      the same logic as today's add_alert_check at
                      posthog/tasks/alerts/checks.py:458-509.
    `new_state`:      AlertState as string (cross-process serialization).
    """

    alert_check_id: int
    should_notify: bool
    new_state: str  # AlertState as string: "Firing" | "Not firing" | "Errored" | "Snoozed"


# ─── notify_alert_activity I/O ──────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class NotifyAlertActivityInputs:
    alert_id: str
    alert_check_id: int


# notify_alert_activity returns None; raises on permanent failure.
