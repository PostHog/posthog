"""Shared alert lifecycle state machine.

Products (logs, billing, ...) each evaluate their own domain data, but the alert
lifecycle — firing, resolving, erroring, breaking, snoozing, cooldown suppression —
is the same machine everywhere. This module is that machine, following the
Prometheus/Alertmanager split: evaluation stays domain-specific in each product,
lifecycle decisions live here, and the contract between them is `CheckInput` in and
`AlertCheckOutcome` out.

Product semantics differ in deliberate, documented ways (e.g. logs never re-notifies
while an alert stays firing; billing re-notifies once per cooldown window). Those
differences are expressed as an `AlertPolicy` so each product is a configuration of
the same decision table rather than a fork of it.

This module is pure Python — no Django, no product imports. Products own persistence:
they build a snapshot from their model, call the machine, and apply the outcome through
their product-local `apply_outcome` (the single legal mutator, enforced by semgrep —
see `.semgrep/rules/alert-state-must-go-through-state-machine.yaml`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, StrEnum
from typing import Protocol

MAX_CONSECUTIVE_FAILURES = 5


class AlertState(StrEnum):
    NOT_FIRING = "not_firing"
    FIRING = "firing"
    # Input-only: accepted from adopters whose models persist it, never produced here.
    PENDING_RESOLVE = "pending_resolve"
    ERRORED = "errored"
    SNOOZED = "snoozed"
    BROKEN = "broken"


class NotificationAction(Enum):
    NONE = "none"
    FIRE = "fire"
    RESOLVE = "resolve"
    ERROR = "error"
    BROKEN = "broken"


class InvalidTransition(Exception):
    """Raised by control-plane transitions when the pre-condition isn't met."""


@dataclass(frozen=True)
class AlertPolicy:
    """Per-product lifecycle semantics. Defaults are the logs alerting behavior.

    Every flag encodes a real, observed divergence between products — do not add a
    flag speculatively, and do not change a default without checking every adopter.
    """

    max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES
    # True (logs): BROKEN is terminal until an explicit user reset. False (billing):
    # a successful check on a BROKEN alert re-evaluates it from scratch — manual
    # check-now is billing's only un-break path.
    broken_is_terminal: bool = True
    # Whether transient errors (e.g. query timeouts) count toward BROKEN.
    transient_errors_count_toward_broken: bool = False
    # False: notify ERROR only on the first transition into ERRORED. True: every failure.
    notify_error_on_every_failure: bool = False
    # False: cooldown only suppresses the re-FIRE of an already-FIRING alert;
    # the first FIRE after a resolve is never suppressed.
    cooldown_gates_initial_fire: bool = True
    cooldown_gates_resolve: bool = True
    # True: an alert that stays breached re-notifies once per cooldown window.
    renotify_while_firing: bool = False
    # False (insights): resolving back to NOT_FIRING is silent.
    notify_on_resolve: bool = True
    # True (billing): snooze only mutes while breached — a clear check resolves and
    # un-snoozes; a breached check parks the alert in SNOOZED without notifying.
    # False (logs): a snoozed alert stays snoozed untouched until snooze_until passes.
    # Known wart: unlike the other flags, this one changes what the SNOOZED state
    # *means* per product, not just when to notify. If a future adopter needs another
    # snooze-adjacent flag, split snooze handling into a strategy instead.
    clear_check_ends_snooze: bool = False
    # True: reaching BROKEN also disables the alert (outcome.disable is set).
    disable_when_broken: bool = False


LOGS_ALERT_POLICY = AlertPolicy()

BILLING_ALERT_POLICY = AlertPolicy(
    broken_is_terminal=False,
    transient_errors_count_toward_broken=True,
    notify_error_on_every_failure=True,
    cooldown_gates_initial_fire=False,
    cooldown_gates_resolve=False,
    renotify_while_firing=True,
    clear_check_ends_snooze=True,
    disable_when_broken=True,
)

# Insight alerts have no cooldown (the calculation interval is the pacing), notify on
# every breached or errored check, resolve silently, and have no failure counter — the
# snapshot always passes consecutive_failures=0, so BROKEN is unreachable.
INSIGHT_ALERT_POLICY = AlertPolicy(
    notify_error_on_every_failure=True,
    cooldown_gates_initial_fire=False,
    cooldown_gates_resolve=False,
    renotify_while_firing=True,
    notify_on_resolve=False,
)


@dataclass(frozen=True)
class CheckInput:
    """Normalized result of one domain evaluation — all the machine needs to know."""

    threshold_breached: bool
    # Evaluation couldn't reach a verdict (e.g. source data not settled yet): state
    # and failure counter are left unchanged and no notification is emitted.
    is_inconclusive: bool = False
    error_message: str | None = None
    is_transient_error: bool = False


@dataclass(frozen=True)
class AlertSnapshot:
    """The fields the machine reads to decide a transition."""

    state: AlertState
    cooldown: timedelta
    last_notified_at: datetime | None
    snooze_until: datetime | None
    consecutive_failures: int
    # N-of-M sliding window (CloudWatch-style). 1-of-1 means "fire on any breach".
    evaluation_periods: int = 1
    datapoints_to_alarm: int = 1
    # Breach flags of the most recent prior checks, newest first (excludes the current one).
    recent_events_breached: tuple[bool, ...] = ()


class StatefulSnapshot(Protocol):
    """What control-plane transitions need — satisfied by any product snapshot type."""

    @property
    def state(self) -> AlertState: ...

    @property
    def consecutive_failures(self) -> int: ...


@dataclass(frozen=True)
class AlertCheckOutcome:
    new_state: AlertState
    notification: NotificationAction
    consecutive_failures: int
    update_last_notified_at: bool
    error_message: str | None
    # Set when policy.disable_when_broken kicks in — the adapter must persist enabled=False.
    disable: bool = False


@dataclass(frozen=True)
class ControlPlaneOutcome:
    """Outcome of a user-initiated or serializer-driven transition.

    Shares `new_state` + `consecutive_failures` with `AlertCheckOutcome` so both
    can flow through a product's `apply_outcome` uniformly.
    """

    new_state: AlertState
    consecutive_failures: int


Outcome = AlertCheckOutcome | ControlPlaneOutcome


def _stay(snapshot: AlertSnapshot) -> AlertCheckOutcome:
    return AlertCheckOutcome(
        new_state=snapshot.state,
        notification=NotificationAction.NONE,
        consecutive_failures=snapshot.consecutive_failures,
        update_last_notified_at=False,
        error_message=None,
    )


def evaluate_alert_check(
    snapshot: AlertSnapshot,
    check: CheckInput,
    now: datetime,
    *,
    policy: AlertPolicy,
) -> AlertCheckOutcome:
    """Decide the transition for one scheduled/manual check.

    N-of-M sliding-window trigger for firing, immediate resolution on the first OK
    window, cooldown suppression per policy, and error escalation to BROKEN.
    """
    if snapshot.state == AlertState.BROKEN and policy.broken_is_terminal:
        # Terminal until a user reset — schedulers already exclude BROKEN alerts,
        # this is belt-and-braces against a race.
        return _stay(snapshot)

    snoozing = snapshot.snooze_until is not None and snapshot.snooze_until > now

    # Guard order is load-bearing: this stay-guard must precede error handling so that
    # products without clear_check_ends_snooze (logs) swallow errors during an active
    # snooze, while products with it (billing) fall through and count them.
    if snapshot.state == AlertState.SNOOZED and snoozing and not policy.clear_check_ends_snooze:
        return _stay(snapshot)

    if check.error_message is not None:
        return evaluate_alert_failure(
            snapshot,
            error_message=check.error_message,
            is_transient_error=check.is_transient_error,
            policy=policy,
        )

    if check.is_inconclusive:
        return AlertCheckOutcome(
            new_state=snapshot.state,
            notification=NotificationAction.NONE,
            consecutive_failures=snapshot.consecutive_failures,
            update_last_notified_at=False,
            error_message=None,
        )

    if snoozing and check.threshold_breached and policy.clear_check_ends_snooze:
        # Breach while muted: park in SNOOZED without notifying, whatever the prior state.
        return AlertCheckOutcome(
            new_state=AlertState.SNOOZED,
            notification=NotificationAction.NONE,
            consecutive_failures=0,
            update_last_notified_at=False,
            error_message=None,
        )

    if snapshot.state == AlertState.SNOOZED:
        # clear_check_ends_snooze: a snoozed alert was breached when parked, so a clear
        # check resolves it (FIRING-like). Otherwise the snooze simply expired and the
        # alert re-evaluates from scratch.
        effective_state = AlertState.FIRING if policy.clear_check_ends_snooze else AlertState.NOT_FIRING
    elif snapshot.state in (AlertState.ERRORED, AlertState.BROKEN):
        # BROKEN is only reachable here when the policy allows checks to un-break.
        effective_state = AlertState.NOT_FIRING
    else:
        effective_state = snapshot.state

    window = [check.threshold_breached, *snapshot.recent_events_breached][: snapshot.evaluation_periods]
    breach_count = sum(1 for b in window if b)
    breached = breach_count >= snapshot.datapoints_to_alarm

    notification = NotificationAction.NONE

    if effective_state == AlertState.NOT_FIRING:
        if breached:
            new_state = AlertState.FIRING
            notification = NotificationAction.FIRE
        else:
            new_state = AlertState.NOT_FIRING

    elif effective_state in (AlertState.FIRING, AlertState.PENDING_RESOLVE):
        if breached:
            new_state = AlertState.FIRING
            if policy.renotify_while_firing:
                notification = NotificationAction.FIRE
        else:
            new_state = AlertState.NOT_FIRING
            if policy.notify_on_resolve:
                notification = NotificationAction.RESOLVE

    else:
        new_state = AlertState.NOT_FIRING

    update_last_notified_at = False
    if notification != NotificationAction.NONE:
        if notification == NotificationAction.FIRE:
            # Raw state, not effective_state: a snooze-expiry refire counts as an
            # initial fire, so it's only gated when the policy gates initial fires.
            gated = policy.cooldown_gates_initial_fire or snapshot.state == AlertState.FIRING
        else:
            gated = policy.cooldown_gates_resolve
        if gated and _is_within_cooldown(snapshot.last_notified_at, snapshot.cooldown, now):
            notification = NotificationAction.NONE
        else:
            update_last_notified_at = True

    return AlertCheckOutcome(
        new_state=new_state,
        notification=notification,
        consecutive_failures=0,
        update_last_notified_at=update_last_notified_at,
        error_message=None,
    )


def evaluate_alert_failure(
    snapshot: AlertSnapshot,
    *,
    error_message: str,
    is_transient_error: bool = False,
    policy: AlertPolicy,
) -> AlertCheckOutcome:
    """Decide the transition for a failed evaluation (query error, upstream outage, ...).

    Callable directly by products whose evaluators raise instead of returning an
    error CheckInput; `evaluate_alert_check` routes here for the rest.
    """
    if is_transient_error and not policy.transient_errors_count_toward_broken:
        consecutive_failures = snapshot.consecutive_failures
    else:
        consecutive_failures = snapshot.consecutive_failures + 1

    new_state = AlertState.BROKEN if consecutive_failures >= policy.max_consecutive_failures else AlertState.ERRORED

    if new_state == AlertState.BROKEN:
        notification = NotificationAction.BROKEN
    elif policy.notify_error_on_every_failure:
        notification = NotificationAction.ERROR
    elif snapshot.state != AlertState.ERRORED:
        # First transition into ERRORED only — repeat failures stay quiet. SNOOZED
        # auto-expiry can't re-trigger this because the raw state is what's checked.
        notification = NotificationAction.ERROR
    else:
        notification = NotificationAction.NONE

    return AlertCheckOutcome(
        new_state=new_state,
        notification=notification,
        consecutive_failures=consecutive_failures,
        update_last_notified_at=False,
        error_message=error_message,
        disable=policy.disable_when_broken and new_state == AlertState.BROKEN,
    )


def apply_user_reset(snapshot: StatefulSnapshot) -> ControlPlaneOutcome:
    if snapshot.state != AlertState.BROKEN:
        raise InvalidTransition(f"Only broken alerts can be reset. Current state is {snapshot.state.value}.")
    return ControlPlaneOutcome(new_state=AlertState.NOT_FIRING, consecutive_failures=0)


def apply_disable(snapshot: StatefulSnapshot) -> ControlPlaneOutcome:
    # Preserve consecutive_failures so re-enable without reset doesn't silently
    # wipe forensic state.
    return ControlPlaneOutcome(
        new_state=AlertState.NOT_FIRING,
        consecutive_failures=snapshot.consecutive_failures,
    )


def apply_enable(snapshot: StatefulSnapshot) -> ControlPlaneOutcome:
    return ControlPlaneOutcome(new_state=AlertState.NOT_FIRING, consecutive_failures=0)


def apply_snooze(snapshot: StatefulSnapshot) -> ControlPlaneOutcome:
    return ControlPlaneOutcome(
        new_state=AlertState.SNOOZED,
        consecutive_failures=snapshot.consecutive_failures,
    )


def apply_unsnooze(snapshot: StatefulSnapshot) -> ControlPlaneOutcome:
    return ControlPlaneOutcome(new_state=AlertState.NOT_FIRING, consecutive_failures=0)


def apply_threshold_change(snapshot: StatefulSnapshot) -> ControlPlaneOutcome:
    # Snoozed alerts stay snoozed on edit — editing configuration must not wake a
    # silenced alert.
    if snapshot.state == AlertState.SNOOZED:
        return ControlPlaneOutcome(
            new_state=AlertState.SNOOZED,
            consecutive_failures=snapshot.consecutive_failures,
        )
    return ControlPlaneOutcome(new_state=AlertState.NOT_FIRING, consecutive_failures=0)


def _is_within_cooldown(
    last_notified_at: datetime | None,
    cooldown: timedelta,
    now: datetime,
) -> bool:
    if cooldown <= timedelta(0) or last_notified_at is None:
        return False
    return now < last_notified_at + cooldown
