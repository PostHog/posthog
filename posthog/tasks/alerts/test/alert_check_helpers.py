"""Shared test helper for trends alert integration tests.

Mimics the behavior of the old `check_alert()` function from
`posthog.tasks.alerts.checks`, which was deleted in PR4 of the
alerts->Temporal migration. The real alert check now runs via the Temporal
`CheckAlertWorkflow` (prepare + evaluate + notify activities), but the trends
integration tests still exercise the evaluation+persistence+notification flow
via a direct helper so they don't need to spin up a Temporal test environment
for every assertion.

Patches targeting the notification functions should point at this module, e.g.::

    @patch("posthog.tasks.alerts.test.alert_check_helpers.send_notifications_for_breaches")

TODO: Delete this helper once the prepare/evaluate/notify activities land in
https://github.com/PostHog/posthog/pull/53835 and the trends tests drive the
Temporal activities directly. Keeping it around is a temporary scaffold so
PR4 can ship independently of the activity bodies.
"""

import traceback

from posthog.schema import AlertState

from posthog.models import AlertConfiguration
from posthog.tasks.alerts.checks import add_alert_check, check_alert_for_insight
from posthog.tasks.alerts.utils import send_notifications_for_breaches, send_notifications_for_errors


def run_alert_check(alert_id: str) -> None:
    """Evaluate an alert, persist the AlertCheck, dispatch notifications."""
    alert = AlertConfiguration.objects.select_related("insight", "team").get(id=alert_id, enabled=True)

    error = None
    result = None
    try:
        result = check_alert_for_insight(alert)
    except Exception as e:
        error = {"message": str(e), "traceback": traceback.format_exc()}

    alert_check = add_alert_check(
        alert,
        value=result.value if result else None,
        breaches=result.breaches if result else None,
        error=error,
        anomaly_scores=result.anomaly_scores if result else None,
        triggered_points=result.triggered_points if result else None,
        triggered_dates=result.triggered_dates if result else None,
        interval=result.interval if result else None,
        triggered_metadata=result.triggered_metadata if result else None,
    )

    if not alert_check.targets_notified:
        return

    if alert_check.state == AlertState.ERRORED:
        assert alert_check.error is not None
        send_notifications_for_errors(alert, alert_check.error)
    elif alert_check.state == AlertState.FIRING:
        assert result is not None and result.breaches is not None
        send_notifications_for_breaches(alert, result.breaches)
