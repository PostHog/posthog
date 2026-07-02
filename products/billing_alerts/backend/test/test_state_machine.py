from datetime import UTC, datetime, timedelta

from unittest import TestCase

from parameterized import parameterized

from common.alerting.state_machine import (
    BILLING_ALERT_POLICY,
    AlertSnapshot,
    AlertState,
    CheckInput,
    NotificationAction,
    evaluate_alert_check,
    evaluate_alert_failure,
)

BROKEN = AlertState.BROKEN
ERRORED = AlertState.ERRORED
FIRING = AlertState.FIRING
NOT_FIRING = AlertState.NOT_FIRING
SNOOZED = AlertState.SNOOZED

NOW = datetime(2026, 3, 19, 12, 0, 0, tzinfo=UTC)


def _snapshot(
    state: AlertState = NOT_FIRING,
    cooldown_hours: int = 0,
    last_notified_at: datetime | None = None,
    snooze_until: datetime | None = None,
    consecutive_failures: int = 0,
) -> AlertSnapshot:
    return AlertSnapshot(
        state=state,
        cooldown=timedelta(hours=cooldown_hours),
        last_notified_at=last_notified_at,
        snooze_until=snooze_until,
        consecutive_failures=consecutive_failures,
    )


def _check(breached: bool = False, inconclusive: bool = False) -> CheckInput:
    return CheckInput(threshold_breached=breached, is_inconclusive=inconclusive)


class TestBillingAlertPolicyContract(TestCase):
    # Pins the BILLING_ALERT_POLICY semantics of the shared machine that billing's
    # DB-backed tests only exercise indirectly. If a change to the shared machine or
    # the policy defaults flips one of these rows, billing behavior changed.

    @parameterized.expand(
        [
            # (name, snapshot, check, expected_state, expected_notification)
            ("initial_fire", _snapshot(NOT_FIRING), _check(breached=True), FIRING, NotificationAction.FIRE),
            (
                # Billing's cooldown never gates the first FIRE after a resolve.
                "initial_fire_not_gated_by_cooldown",
                _snapshot(NOT_FIRING, cooldown_hours=24, last_notified_at=NOW - timedelta(hours=1)),
                _check(breached=True),
                FIRING,
                NotificationAction.FIRE,
            ),
            (
                # A still-breached alert re-notifies once per cooldown window.
                "renotify_after_cooldown_expires",
                _snapshot(FIRING, cooldown_hours=1, last_notified_at=NOW - timedelta(hours=2)),
                _check(breached=True),
                FIRING,
                NotificationAction.FIRE,
            ),
            (
                "renotify_suppressed_within_cooldown",
                _snapshot(FIRING, cooldown_hours=24, last_notified_at=NOW - timedelta(hours=1)),
                _check(breached=True),
                FIRING,
                NotificationAction.NONE,
            ),
            (
                "resolve_not_gated_by_cooldown",
                _snapshot(FIRING, cooldown_hours=24, last_notified_at=NOW - timedelta(hours=1)),
                _check(breached=False),
                NOT_FIRING,
                NotificationAction.RESOLVE,
            ),
            (
                # Breach while snoozed parks the alert in SNOOZED without notifying,
                # whatever the prior state.
                "breach_during_snooze_parks_snoozed",
                _snapshot(NOT_FIRING, snooze_until=NOW + timedelta(days=1)),
                _check(breached=True),
                SNOOZED,
                NotificationAction.NONE,
            ),
            (
                # A clear check ends the snooze and resolves — billing snooze only
                # mutes while breached.
                "clear_check_ends_snooze_and_resolves",
                _snapshot(SNOOZED, snooze_until=NOW + timedelta(days=1)),
                _check(breached=False),
                NOT_FIRING,
                NotificationAction.RESOLVE,
            ),
            (
                "snooze_expiry_refires",
                _snapshot(SNOOZED, snooze_until=NOW - timedelta(hours=1)),
                _check(breached=True),
                FIRING,
                NotificationAction.FIRE,
            ),
            (
                # check_now is billing's only un-break path: a successful check on a
                # BROKEN alert re-evaluates from scratch instead of staying terminal.
                "broken_unbreaks_on_breached_check",
                _snapshot(BROKEN, consecutive_failures=5),
                _check(breached=True),
                FIRING,
                NotificationAction.FIRE,
            ),
            (
                "broken_unbreaks_on_clear_check",
                _snapshot(BROKEN, consecutive_failures=5),
                _check(breached=False),
                NOT_FIRING,
                NotificationAction.NONE,
            ),
            (
                "inconclusive_leaves_state_unchanged",
                _snapshot(FIRING),
                _check(breached=False, inconclusive=True),
                FIRING,
                NotificationAction.NONE,
            ),
        ]
    )
    def test_check_transitions(
        self,
        _name: str,
        snapshot: AlertSnapshot,
        check: CheckInput,
        expected_state: AlertState,
        expected_notification: NotificationAction,
    ) -> None:
        outcome = evaluate_alert_check(snapshot, check, NOW, policy=BILLING_ALERT_POLICY)
        assert outcome.new_state == expected_state
        assert outcome.notification == expected_notification
        assert outcome.consecutive_failures == 0

    def test_inconclusive_preserves_consecutive_failures(self) -> None:
        # An inconclusive verdict while ERRORED must not reset the failure counter,
        # or BROKEN escalation gets silently delayed.
        outcome = evaluate_alert_check(
            _snapshot(ERRORED, consecutive_failures=3),
            _check(breached=False, inconclusive=True),
            NOW,
            policy=BILLING_ALERT_POLICY,
        )
        assert outcome.new_state == ERRORED
        assert outcome.notification == NotificationAction.NONE
        assert outcome.consecutive_failures == 3

    @parameterized.expand(
        [
            # Transient errors count toward BROKEN for billing (unlike logs).
            ("transient_counts", True),
            ("permanent_counts", False),
        ]
    )
    def test_failures_escalate_to_broken_and_disable(self, _name: str, is_transient: bool) -> None:
        outcome = evaluate_alert_failure(
            _snapshot(ERRORED, consecutive_failures=4),
            error_message="billing api down",
            is_transient_error=is_transient,
            policy=BILLING_ALERT_POLICY,
        )
        assert outcome.new_state == BROKEN
        assert outcome.notification == NotificationAction.BROKEN
        assert outcome.consecutive_failures == 5
        assert outcome.disable is True

    def test_every_failure_notifies_error(self) -> None:
        outcome = evaluate_alert_failure(
            _snapshot(ERRORED, consecutive_failures=1),
            error_message="billing api down",
            policy=BILLING_ALERT_POLICY,
        )
        assert outcome.new_state == ERRORED
        assert outcome.notification == NotificationAction.ERROR
        assert outcome.disable is False
