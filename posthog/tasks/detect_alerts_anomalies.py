from typing import cast

import structlog
from celery import shared_task
from django.utils import timezone

from posthog.email import EmailMessage
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Alert, AnomalyCondition
from posthog.schema import HogQLQueryResponse

logger = structlog.get_logger(__name__)


def check_all_alerts() -> None:
    alerts = Alert.objects.all().only("id")
    for alert in alerts:
        logger.info("scheduling alert", alert_id=alert.id)
        check_alert.delay(alert.id)


@shared_task(ignore_result=True)
def check_alert(id: int) -> None:
    alert = Alert.objects.get(pk=id)
    insight = alert.insight
    if not insight.query:
        insight.query = filter_to_query(insight.filters)
    query_runner = get_query_runner(insight.query, alert.team)
    response = cast(HogQLQueryResponse, query_runner.calculate())
    if not response.results:
        raise RuntimeError(f"no results for alert {alert.id}")

    anomaly_condition = AnomalyCondition(**alert.anomaly_condition)
    thresholds = anomaly_condition.absolute_threshold

    result = response.results[0]
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
        logger.info("no anomalies", alert_id=alert.id)
        return

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
