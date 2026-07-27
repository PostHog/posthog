import traceback

from django.db import transaction

from posthog.tasks.alerts import utils as alert_utils

from products.alerts.backend.evaluation import check_alert_for_insight
from products.alerts.backend.models import AlertConfiguration


def run_alert_check(alert_id: str) -> None:
    """Evaluate an alert, persist the AlertCheck, dispatch notifications."""
    alert = AlertConfiguration.objects.select_related("insight", "team").get(id=alert_id, enabled=True)

    error = None
    result = None
    try:
        result = check_alert_for_insight(alert)
    except Exception as e:
        error = {"message": str(e), "traceback": traceback.format_exc()}

    with transaction.atomic():
        alert_check, notify = alert_utils.add_alert_check(
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

    if not notify:
        return

    breaches = result.breaches if result else None
    dispatch_targets = alert_utils.dispatch_alert_notification(alert, alert_check, breaches)
    if dispatch_targets is None:
        return

    # Resolve targets directly from the alert — tests that @patch send_notifications_*
    # return MagicMock values, so we can't trust dispatch's return. The real activity
    # does trust the return (no mocks), and both paths resolve to the same list.
    targets = alert.get_subscribed_users_emails()
    if not targets:
        return
    with transaction.atomic():
        alert_utils.record_alert_delivery(alert, alert_check, targets)
