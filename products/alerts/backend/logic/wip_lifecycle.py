"""The single legal mutator for skeleton alert state.

A source decides whether its data breached; the shared lifecycle decides what that means for
the alert. Keeping the write here means a source never sets `state` itself, which is the rule
each product's own alert tables already follow.
"""

from datetime import datetime

from products.alerts.backend.facade.lifecycle import AlertCheckOutcome
from products.alerts.backend.facade.scheduling import advance_next_check_at
from products.alerts.backend.models import WIPAlert, WIPAlertConfiguration


def apply_outcome(
    configuration: WIPAlertConfiguration, alert: WIPAlert, outcome: AlertCheckOutcome, now: datetime
) -> None:
    """Persists one check's decision and advances the configuration's schedule."""
    alert.state = outcome.new_state.value
    if outcome.update_last_notified_at:
        alert.last_notified_at = now
    alert.save(update_fields=["state", "last_notified_at"])

    configuration.consecutive_failures = outcome.consecutive_failures
    configuration.next_check_at = advance_next_check_at(
        configuration.next_check_at, configuration.check_interval_minutes, now
    )
    configuration.save(update_fields=["consecutive_failures", "next_check_at"])
