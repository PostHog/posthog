from celery import shared_task
from celery.canvas import group, chain
from django.utils import timezone
import math
import structlog

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.email import EmailMessage
from posthog.hogql_queries.legacy_compatibility.flagged_conversion_manager import (
    conversion_to_query_based,
)
from posthog.models import Alert
from posthog.schema import AnomalyCondition

logger = structlog.get_logger(__name__)


def check_all_alerts() -> None:
    alert_ids = list(Alert.objects.all().values_list("id", flat=True))

    group_count = 10
    # All groups but the last one will have a group_size size.
    # The last group will have at most group_size size.
    group_size = int(math.ceil(len(alert_ids) / group_count))

    groups = []
    for i in range(0, len(alert_ids), group_size):
        alert_id_group = alert_ids[i : i + group_size]
        chained_calls = chain([check_alert_task.si(alert_id) for alert_id in alert_id_group])
        groups.append(chained_calls)

    group(groups).apply_async()


def check_alert(alert_id: int) -> None:
    alert = Alert.objects.get(pk=alert_id)
    insight = alert.insight

    with conversion_to_query_based(insight):
        calculation_result = calculate_for_query_based_insight(
            insight,
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            user=None,
        )

    if not calculation_result.result:
        raise RuntimeError(f"No results for alert {alert.id}")

    anomaly_condition = AnomalyCondition.model_validate(alert.anomaly_condition)
    thresholds = anomaly_condition.absoluteThreshold

    result = calculation_result.result[0]
    aggregated_value = result["aggregated_value"]
    anomalies_descriptions = []

    if thresholds.lower is not None and aggregated_value < thresholds.lower:
        anomalies_descriptions += [
            f"The trend value ({aggregated_value}) is below the lower threshold ({thresholds.lower})"
        ]
    if thresholds.upper is not None and aggregated_value > thresholds.upper:
        anomalies_descriptions += [
            f"The trend value ({aggregated_value}) is above the upper threshold ({thresholds.upper})"
        ]

    if not anomalies_descriptions:
        logger.info("No threshold met", alert_id=alert.id)
        return

    send_notifications(alert, anomalies_descriptions)


@shared_task(ignore_result=True)
def check_all_alerts_task() -> None:
    check_all_alerts()


@shared_task(ignore_result=True)
def check_alert_task(alert_id: int) -> None:
    check_alert(alert_id)


def send_notifications(alert: Alert, anomalies_descriptions: list[str]) -> None:
    subject = f"PostHog alert {alert.name} has anomalies"
    campaign_key = f"alert-anomaly-notification-{alert.id}-{timezone.now().timestamp()}"
    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
    alert_url = f"{insight_url}/alerts/{alert.id}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="alert_anomaly",
        template_context={
            "anomalies_descriptions": anomalies_descriptions,
            "insight_url": insight_url,
            "insight_name": alert.insight.name,
            "alert_url": alert_url,
            "alert_name": alert.name,
        },
    )
    targets = list(filter(len, alert.target_value.split(",")))
    if not targets:
        raise RuntimeError(f"no targets configured for the alert {alert.id}")
    for target in targets:
        message.add_recipient(email=target)

    logger.info(f"Send notifications about {len(anomalies_descriptions)} anomalies", alert_id=alert.id)
    message.send()
