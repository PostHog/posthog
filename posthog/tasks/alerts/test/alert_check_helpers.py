import traceback

from django.db import transaction

from posthog.tasks.alerts import utils as alert_utils
from posthog.tasks.alerts.metrics_investigation import run_metrics_alert_investigation, should_investigate_metrics_alert
from posthog.temporal.alerts.investigation import claim_investigation_slot

from products.alerts.backend.evaluation import check_alert_for_insight
from products.alerts.backend.models import AlertConfiguration


def run_alert_check(alert_id: str) -> None:
    """Evaluate an alert, persist the AlertCheck, dispatch notifications."""
    alert = AlertConfiguration.objects.select_related("insight", "team").get(id=alert_id, enabled=True)

    error = None
    result = None
    previous_state = alert.state
    try:
        result = check_alert_for_insight(alert)
    except Exception as e:
        error = {"message": str(e), "traceback": traceback.format_exc()}

    should_run_metrics_investigation = False
    with transaction.atomic():
        alert_check, notify = alert_utils.add_alert_check(alert, result, error)

        # Claim the cooldown slot inside the transaction (read-then-write stays
        # consistent with the check insert), mirroring the detector path.
        if should_investigate_metrics_alert(
            alert, previous_state=previous_state, new_state=alert_check.state
        ) and claim_investigation_slot(alert, alert_check):
            should_run_metrics_investigation = True

    # Outside the persistence transaction: the investigation issues ClickHouse
    # queries and must never hold the row lock or affect the check outcome.
    if should_run_metrics_investigation:
        run_metrics_alert_investigation(alert, alert_check)

    if not notify:
        return

    breaches = result.breaches if result else None
    deliveries = alert_utils.dispatch_alert_notification(alert, alert_check, breaches)
    if deliveries is None:
        return

    with transaction.atomic():
        alert_utils.record_alert_delivery(alert, alert_check, deliveries)
