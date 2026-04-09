from datetime import UTC, datetime

from django.db.models import Case, F, IntegerField, Q, Value, When

import structlog
import temporalio.activity

from posthog.schema import AlertCalculationInterval

from posthog.models import AlertConfiguration
from posthog.sync import database_sync_to_async
from posthog.temporal.alerts.types import (
    AlertInfo,
    EvaluateAlertActivityInputs,
    EvaluateAlertResult,
    NotifyAlertActivityInputs,
    PrepareAlertActivityInputs,
    PrepareAlertResult,
)

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def retrieve_due_alerts() -> list[AlertInfo]:
    @database_sync_to_async(thread_sensitive=False)
    def get_alerts() -> list[AlertInfo]:
        now = datetime.now(UTC)

        # Hourly before daily before weekly/monthly so the cheaper, more
        # time-sensitive checks get workers first when the due batch is large.
        calculation_interval_order = Case(
            When(calculation_interval=AlertCalculationInterval.HOURLY.value, then=Value(0)),
            When(calculation_interval=AlertCalculationInterval.DAILY.value, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )

        alerts = (
            AlertConfiguration.objects.filter(
                Q(enabled=True, next_check_at__lte=now) | Q(enabled=True, next_check_at__isnull=True)
            )
            .filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=now))
            .filter(insight__deleted=False)
            .annotate(_interval_order=calculation_interval_order)
            .order_by("_interval_order", F("next_check_at").asc(nulls_first=True))
            .only("id", "team_id", "calculation_interval", "insight_id")
        )

        return [
            AlertInfo(
                alert_id=str(a.id),
                team_id=a.team_id,
                distinct_id=str(a.id),
                calculation_interval=a.calculation_interval,
                insight_id=a.insight_id,
            )
            for a in alerts
        ]

    return await get_alerts()


# ─── prepare_alert_activity ─────────────────────────────────────────
# TODO(vasco): Port the early-return logic that used to live in check_alert()
# in posthog/tasks/alerts/checks.py. The check_alert function is deleted in
# the final cleanup PR of this stack — reference it via git history:
#
#   git show vdekrijger-alerts-temporal-pr1-scaffolding:posthog/tasks/alerts/checks.py
#
# Shape of the port:
#
#   1. Load AlertConfiguration by id with select_related (pre-cleanup checks.py:230-233)
#      → if DoesNotExist: return PrepareAlertResult(action="skip", reason="not_found")
#
#   2. Check insight.deleted (checks.py:235-237)
#      → return PrepareAlertResult(action="skip", reason="insight_deleted")
#
#   3. Check next_check_at race window (checks.py:241-247)
#      → return PrepareAlertResult(action="skip", reason="not_due")
#
#      (No is_calculating check — the field is removed later in the stack and
#      Temporal's deterministic workflow ID guarantee replaces the lock.)
#
#   4. Check skip_because_of_weekend + advance next_check_at (checks.py:256-265)
#      → return PrepareAlertResult(action="skip", reason="weekend")
#
#   5. Check is_utc_datetime_blocked + advance next_check_at (checks.py:267-274)
#      → return PrepareAlertResult(action="skip", reason="quiet_hours")
#
#   6. Check snoozed_until (checks.py:276-286)
#      → return PrepareAlertResult(action="skip", reason="snoozed")
#
#   7. Validate config (checks.py:288-296). On ValueError:
#      → call disable_invalid_alert from posthog.tasks.alerts.utils (imported
#        inside the sync helper to satisfy the late-imports policy).
#      → return PrepareAlertResult(action="auto_disable", reason=str(e))
#
#   8. If we got here: return PrepareAlertResult(action="evaluate")
#
# All DB work happens via sync_to_async like enumerate_due_alerts_activity.
@temporalio.activity.defn
async def prepare_alert(inputs: PrepareAlertActivityInputs) -> PrepareAlertResult:
    """Load the alert, validate its config, and decide whether to evaluate."""
    raise NotImplementedError(
        "Alert check logic is ported in follow-up PR: https://github.com/PostHog/posthog/pull/53835"
    )


# ─── evaluate_alert_activity ────────────────────────────────────────
# TODO(vasco): Port the alert evaluation logic from the deleted
# check_alert_and_notify_atomically in pre-cleanup checks.py. Shape of the port:
#
#   1. Load AlertConfiguration by id (alert was already validated in prepare).
#      No is_calculating lock needed — the field is removed later in the stack
#      and Temporal's deterministic workflow ID guarantee replaces the lock.
#
#   2. CRITICAL — call tag_queries(alert_config_id=str(alert.id)) at the START
#      of the activity body (pre-cleanup checks.py:341). This is what lets
#      ClickHouse workload management classify alert queries differently from
#      other queries on the cluster. The "drop per-team serialization, rely on
#      CH workload management" design depends on this tag being present on
#      every CH query the activity issues. Don't skip it.
#
#   3. Run check_alert_for_insight (still in checks.py) inside @transaction.atomic
#      → returns AlertEvaluationResult with value, breaches, anomaly_scores, etc
#      → on CH transient error: re-raise (Temporal retry policy handles it)
#      → on permanent error: capture in `error` variable, continue
#
#   4. Run add_alert_check (still in checks.py) — but extract the notification
#      decision into the result instead of inlining it. The current code sets
#      notify=True inside add_alert_check; we want to RETURN that decision so
#      the workflow can route to notify_alert_activity instead of doing it here.
#      CRITICAL: create the AlertCheck row with `targets_notified={}` always —
#      do NOT call alert.get_subscribed_users_emails() here. The notify activity
#      sets targets_notified on success and uses an empty value as the
#      idempotency sentinel. See the notify_alert_activity TODO below for the
#      full contract change.
#
#   5. Return EvaluateAlertResult(alert_check_id=..., should_notify=..., new_state=...)
#
# The CH transient error retry from tenacity on the pre-cleanup check_alert is
# REPLACED by the ALERT_EVALUATE_RETRY_POLICY on the activity — do not port the
# @retry decorator.
#
# The CH query is synchronous Django ORM/HogQL work; dispatch it with
# sync_to_async and wrap in the existing Heartbeater context manager from
# posthog.temporal.common.heartbeat so Temporal can detect a stuck activity.
@temporalio.activity.defn
async def evaluate_alert(inputs: EvaluateAlertActivityInputs) -> EvaluateAlertResult:
    """Run the insight ClickHouse query, apply the state machine, persist an AlertCheck row."""
    raise NotImplementedError(
        "Alert check logic is ported in follow-up PR: https://github.com/PostHog/posthog/pull/53835"
    )


# ─── notify_alert_activity ──────────────────────────────────────────
# TODO(vasco): Port the notification dispatch from pre-cleanup
# checks.py:383-405 (check_alert_and_notify_atomically's notification block).
#
# AlertCheck row commit semantics change — read before porting:
#
# Pre-migration, check_alert_and_notify_atomically was wrapped in
# @transaction.atomic so the AlertCheck row creation and notification dispatch
# shared a transaction. If notification raised, the transaction rolled back and
# the AlertCheck row was never persisted. The contract was:
#
#   AlertCheck row exists in DB ⇒ evaluation completed AND
#                                  (notification was unnecessary OR
#                                   notification succeeded on this attempt)
#
# Under the split-activity design, evaluate_alert_activity commits the
# AlertCheck row BEFORE notify_alert_activity runs. If notify fails and is
# retried by Temporal, the row is visible the whole time with
# `targets_notified={}`. The new contract is:
#
#   AlertCheck row exists in DB ⇒ evaluation completed
#                                  (notification status is reflected in
#                                   targets_notified populated/empty)
#
# Idempotency under retry:
#   1. Load AlertCheck by id
#   2. If alert_check.targets_notified is already populated AND non-empty:
#        → return (already notified on a previous attempt)
#   3. match alert_check.state (same as pre-cleanup checks.py:387-396):
#        - NOT_FIRING: log and return
#        - ERRORED:    send_notifications_for_errors
#        - FIRING:     send_notifications_for_breaches
#   4. On success: update alert_check.targets_notified =
#        {"users": alert.get_subscribed_users_emails()} and save
#   5. On failure: raise — Temporal retry policy handles backoff
@temporalio.activity.defn
async def notify_alert(inputs: NotifyAlertActivityInputs) -> None:
    """Send notifications for a previously evaluated alert check (idempotent)."""
    raise NotImplementedError(
        "Alert check logic is ported in follow-up PR: https://github.com/PostHog/posthog/pull/53835"
    )
