from datetime import UTC, datetime, timedelta

from unittest import TestCase

from parameterized import parameterized

from posthog.schema_enums import AlertState

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.state_machine import decide_insight_alert_check

NOW = datetime(2026, 3, 19, 12, 0, 0, tzinfo=UTC)


def _alert(
    state: AlertState = AlertState.NOT_FIRING,
    last_notified_at: datetime | None = None,
    snoozed_until: datetime | None = None,
) -> AlertConfiguration:
    return AlertConfiguration(
        state=state,
        last_notified_at=last_notified_at,
        snoozed_until=snoozed_until,
    )


class TestInsightAlertPolicyContract(TestCase):
    # Pins the INSIGHT_ALERT_POLICY semantics of the shared machine — the riskiest
    # adoption (every insight alert check routes through it). If a change to the
    # shared machine or policy defaults flips one of these rows, insight alert
    # behavior changed.

    @parameterized.expand(
        [
            # (name, alert, breached, error_message, expected_state, expected_notify)
            ("initial_fire", _alert(), True, None, AlertState.FIRING, True),
            (
                # No cooldown: a still-breached alert notifies on every check.
                "refire_while_firing_notifies",
                _alert(AlertState.FIRING, last_notified_at=NOW - timedelta(minutes=1)),
                True,
                None,
                AlertState.FIRING,
                True,
            ),
            ("resolve_is_silent", _alert(AlertState.FIRING), False, None, AlertState.NOT_FIRING, False),
            ("clear_check_stays_silent", _alert(), False, None, AlertState.NOT_FIRING, False),
            ("error_notifies", _alert(), False, "query failed", AlertState.ERRORED, True),
            (
                # Repeat errors keep notifying (no first-transition gating for insights).
                "repeat_error_notifies",
                _alert(AlertState.ERRORED),
                False,
                "query failed",
                AlertState.ERRORED,
                True,
            ),
            ("breach_after_error_fires", _alert(AlertState.ERRORED), True, None, AlertState.FIRING, True),
            (
                # Documented divergence: actively snoozed checks stay snoozed silently.
                # Unreachable in the scheduled path (prepare skips snoozed alerts) —
                # this row pins the safe fallback for any other caller.
                "actively_snoozed_stays_silent",
                _alert(AlertState.SNOOZED, snoozed_until=NOW + timedelta(days=1)),
                True,
                None,
                AlertState.SNOOZED,
                False,
            ),
            (
                "expired_snooze_refires",
                _alert(AlertState.SNOOZED, snoozed_until=NOW - timedelta(hours=1)),
                True,
                None,
                AlertState.FIRING,
                True,
            ),
            (
                "expired_snooze_clear_is_silent",
                _alert(AlertState.SNOOZED, snoozed_until=NOW - timedelta(hours=1)),
                False,
                None,
                AlertState.NOT_FIRING,
                False,
            ),
        ]
    )
    def test_check_decisions(
        self,
        _name: str,
        alert,
        breached: bool,
        error_message: str | None,
        expected_state: AlertState,
        expected_notify: bool,
    ) -> None:
        new_state, notify = decide_insight_alert_check(
            alert,
            threshold_breached=breached,
            error_message=error_message,
            now=NOW,
        )
        assert new_state == expected_state
        assert notify is expected_notify
