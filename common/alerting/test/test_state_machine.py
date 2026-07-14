from datetime import UTC, datetime, timedelta

from parameterized import parameterized

from common.alerting.state_machine import (
    LOGS_ALERT_POLICY,
    AlertCheckOutcome,
    AlertPolicy,
    AlertSnapshot,
    AlertState,
    CheckInput,
    NotificationAction,
    evaluate_alert_check,
)

NOW = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)

BREACH = CheckInput(threshold_breached=True)
CLEAR = CheckInput(threshold_breached=False)
ERROR = CheckInput(threshold_breached=False, error_message="query failed")
TRANSIENT_ERROR = CheckInput(threshold_breached=False, error_message="timeout", is_transient_error=True)
INCONCLUSIVE = CheckInput(threshold_breached=False, is_inconclusive=True)

# Non-default flags one at a time, so a broken flag branch fails its own row.
UNBREAKABLE = AlertPolicy(broken_is_terminal=False)
TRANSIENT_BREAKS = AlertPolicy(transient_errors_count_toward_broken=True)
NOISY_ERRORS = AlertPolicy(notify_error_on_every_failure=True)
UNGATED_FIRST_FIRE = AlertPolicy(cooldown_gates_initial_fire=False)
UNGATED_RESOLVE = AlertPolicy(cooldown_gates_resolve=False)
RENOTIFY = AlertPolicy(renotify_while_firing=True)
SNOOZE_UNTIL_CLEAR = AlertPolicy(clear_check_ends_snooze=True)
DISABLE_ON_BROKEN = AlertPolicy(disable_when_broken=True)
BREAKS_EARLY = AlertPolicy(max_consecutive_failures=2)


def snapshot(**overrides) -> AlertSnapshot:
    defaults: dict = {
        "state": AlertState.NOT_FIRING,
        "cooldown": timedelta(minutes=30),
        "last_notified_at": None,
        "snooze_until": None,
        "consecutive_failures": 0,
    }
    return AlertSnapshot(**{**defaults, **overrides})


IN_COOLDOWN = NOW - timedelta(minutes=5)
SNOOZING = NOW + timedelta(hours=1)


class TestPolicyDecisionTable:
    @parameterized.expand(
        [
            # broken_is_terminal=False: a check on a BROKEN alert re-evaluates from scratch
            (
                "unbreak_clear",
                UNBREAKABLE,
                snapshot(state=AlertState.BROKEN),
                CLEAR,
                AlertState.NOT_FIRING,
                NotificationAction.NONE,
            ),
            (
                "unbreak_breach",
                UNBREAKABLE,
                snapshot(state=AlertState.BROKEN),
                BREACH,
                AlertState.FIRING,
                NotificationAction.FIRE,
            ),
            (
                "terminal_broken_ignores_breach",
                LOGS_ALERT_POLICY,
                snapshot(state=AlertState.BROKEN),
                BREACH,
                AlertState.BROKEN,
                NotificationAction.NONE,
            ),
            # transient_errors_count_toward_broken
            (
                "transient_error_spared",
                LOGS_ALERT_POLICY,
                snapshot(state=AlertState.ERRORED, consecutive_failures=4),
                TRANSIENT_ERROR,
                AlertState.ERRORED,
                NotificationAction.NONE,
            ),
            (
                "transient_error_breaks",
                TRANSIENT_BREAKS,
                snapshot(state=AlertState.ERRORED, consecutive_failures=4),
                TRANSIENT_ERROR,
                AlertState.BROKEN,
                NotificationAction.BROKEN,
            ),
            # max_consecutive_failures: breaks at the policy's threshold, not the default constant
            (
                "custom_failure_threshold_breaks",
                BREAKS_EARLY,
                snapshot(state=AlertState.ERRORED, consecutive_failures=1),
                ERROR,
                AlertState.BROKEN,
                NotificationAction.BROKEN,
            ),
            # notify_error_on_every_failure
            (
                "repeat_error_quiet",
                LOGS_ALERT_POLICY,
                snapshot(state=AlertState.ERRORED, consecutive_failures=1),
                ERROR,
                AlertState.ERRORED,
                NotificationAction.NONE,
            ),
            (
                "repeat_error_notifies",
                NOISY_ERRORS,
                snapshot(state=AlertState.ERRORED, consecutive_failures=1),
                ERROR,
                AlertState.ERRORED,
                NotificationAction.ERROR,
            ),
            # cooldown_gates_initial_fire
            (
                "initial_fire_gated",
                LOGS_ALERT_POLICY,
                snapshot(last_notified_at=IN_COOLDOWN),
                BREACH,
                AlertState.FIRING,
                NotificationAction.NONE,
            ),
            (
                "initial_fire_ungated",
                UNGATED_FIRST_FIRE,
                snapshot(last_notified_at=IN_COOLDOWN),
                BREACH,
                AlertState.FIRING,
                NotificationAction.FIRE,
            ),
            # cooldown never spares the re-fire of an already-FIRING alert, even ungated
            (
                "refire_still_gated",
                AlertPolicy(cooldown_gates_initial_fire=False, renotify_while_firing=True),
                snapshot(state=AlertState.FIRING, last_notified_at=IN_COOLDOWN),
                BREACH,
                AlertState.FIRING,
                NotificationAction.NONE,
            ),
            # cooldown_gates_resolve
            (
                "resolve_gated",
                LOGS_ALERT_POLICY,
                snapshot(state=AlertState.FIRING, last_notified_at=IN_COOLDOWN),
                CLEAR,
                AlertState.NOT_FIRING,
                NotificationAction.NONE,
            ),
            (
                "resolve_ungated",
                UNGATED_RESOLVE,
                snapshot(state=AlertState.FIRING, last_notified_at=IN_COOLDOWN),
                CLEAR,
                AlertState.NOT_FIRING,
                NotificationAction.RESOLVE,
            ),
            # renotify_while_firing
            (
                "refire_quiet",
                LOGS_ALERT_POLICY,
                snapshot(state=AlertState.FIRING),
                BREACH,
                AlertState.FIRING,
                NotificationAction.NONE,
            ),
            (
                "refire_notifies",
                RENOTIFY,
                snapshot(state=AlertState.FIRING),
                BREACH,
                AlertState.FIRING,
                NotificationAction.FIRE,
            ),
            # clear_check_ends_snooze
            (
                "snoozed_stays_untouched",
                LOGS_ALERT_POLICY,
                snapshot(state=AlertState.SNOOZED, snooze_until=SNOOZING),
                CLEAR,
                AlertState.SNOOZED,
                NotificationAction.NONE,
            ),
            (
                "breach_parks_in_snooze",
                SNOOZE_UNTIL_CLEAR,
                snapshot(state=AlertState.FIRING, snooze_until=SNOOZING),
                BREACH,
                AlertState.SNOOZED,
                NotificationAction.NONE,
            ),
            (
                "clear_ends_snooze_and_resolves",
                SNOOZE_UNTIL_CLEAR,
                snapshot(state=AlertState.SNOOZED, snooze_until=SNOOZING, cooldown=timedelta(0)),
                CLEAR,
                AlertState.NOT_FIRING,
                NotificationAction.RESOLVE,
            ),
            # snooze expiry under defaults: re-evaluates from scratch, breach is an initial fire
            (
                "expired_snooze_refires",
                LOGS_ALERT_POLICY,
                snapshot(state=AlertState.SNOOZED, snooze_until=NOW - timedelta(minutes=1)),
                BREACH,
                AlertState.FIRING,
                NotificationAction.FIRE,
            ),
            # inconclusive: state and failure counter untouched
            (
                "inconclusive_preserves_state",
                LOGS_ALERT_POLICY,
                snapshot(state=AlertState.ERRORED, consecutive_failures=3),
                INCONCLUSIVE,
                AlertState.ERRORED,
                NotificationAction.NONE,
            ),
        ]
    )
    def test_decision(
        self,
        _name: str,
        policy: AlertPolicy,
        snap: AlertSnapshot,
        check: CheckInput,
        expected_state: AlertState,
        expected_notification: NotificationAction,
    ) -> None:
        outcome = evaluate_alert_check(snap, check, NOW, policy=policy)
        assert outcome.new_state == expected_state
        assert outcome.notification == expected_notification

    def test_inconclusive_preserves_failure_counter(self) -> None:
        outcome = evaluate_alert_check(
            snapshot(state=AlertState.ERRORED, consecutive_failures=3), INCONCLUSIVE, NOW, policy=LOGS_ALERT_POLICY
        )
        assert outcome.consecutive_failures == 3

    @parameterized.expand(
        [
            ("default_keeps_enabled", LOGS_ALERT_POLICY, False),
            ("policy_disables", DISABLE_ON_BROKEN, True),
        ]
    )
    def test_disable_when_broken(self, _name: str, policy: AlertPolicy, expected_disable: bool) -> None:
        outcome = evaluate_alert_check(
            snapshot(state=AlertState.ERRORED, consecutive_failures=4), ERROR, NOW, policy=policy
        )
        assert outcome == AlertCheckOutcome(
            new_state=AlertState.BROKEN,
            notification=NotificationAction.BROKEN,
            consecutive_failures=5,
            update_last_notified_at=False,
            error_message="query failed",
            disable=expected_disable,
        )
