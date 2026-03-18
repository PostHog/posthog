import time

from django.conf import settings

import structlog
from prometheus_client import Gauge

from posthog.dags.common.health.types import BatchResult
from posthog.exceptions_capture import capture_exception
from posthog.metrics import pushed_metrics_registry

logger = structlog.get_logger(__name__)


def push_health_check_metrics(kind: str, totals: BatchResult, *, success: bool = True) -> None:
    if not settings.PROM_PUSHGATEWAY_ADDRESS:
        return

    try:
        with pushed_metrics_registry(f"health_check_{kind}") as registry:
            duration_gauge = Gauge(
                "posthog_health_check_duration_seconds",
                "Duration per phase",
                labelnames=["kind", "phase"],
                registry=registry,
            )
            for phase, value in [
                ("detect", totals.detect_duration),
                ("db_write", totals.db_write_duration),
                ("resolve", totals.resolve_duration),
                ("total", totals.total_duration),
            ]:
                duration_gauge.labels(kind=kind, phase=phase).set(value)

            teams_gauge = Gauge(
                "posthog_health_check_teams",
                "Team counts by outcome",
                labelnames=["kind", "outcome"],
                registry=registry,
            )
            for outcome, value in [
                ("total", totals.batch_size),
                ("with_issues", totals.teams_with_issues),
                ("healthy", totals.teams_healthy),
                ("failed", totals.teams_failed),
                ("skipped", totals.teams_skipped),
            ]:
                teams_gauge.labels(kind=kind, outcome=outcome).set(value)

            issues_gauge = Gauge(
                "posthog_health_check_issues",
                "Issue counts by action",
                labelnames=["kind", "action"],
                registry=registry,
            )
            issues_gauge.labels(kind=kind, action="upserted").set(totals.issues_upserted)
            issues_gauge.labels(kind=kind, action="resolved").set(totals.issues_resolved)

            teams_per_second_gauge = Gauge(
                "posthog_health_check_teams_per_second",
                "Processing throughput",
                labelnames=["kind"],
                registry=registry,
            )
            teams_per_second_gauge.labels(kind=kind).set(totals.teams_per_second)

            success_gauge = Gauge(
                "posthog_health_check_success",
                "1 = OK, 0 = threshold exceeded",
                labelnames=["kind"],
                registry=registry,
            )
            success_gauge.labels(kind=kind).set(1 if success else 0)

            error_rate_gauge = Gauge(
                "posthog_health_check_error_rate",
                "Fraction of teams failed or skipped",
                labelnames=["kind"],
                registry=registry,
            )
            error_rate_gauge.labels(kind=kind).set(totals.not_processed_rate)

            last_run_gauge = Gauge(
                "posthog_health_check_last_run_timestamp",
                "Unix epoch of last run for staleness alerts",
                labelnames=["kind"],
                registry=registry,
            )
            last_run_gauge.labels(kind=kind).set(time.time())
    except Exception as e:
        logger.warning("Failed to push health check metrics to Pushgateway", error=str(e), kind=kind)
        capture_exception(e)
