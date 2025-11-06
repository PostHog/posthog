import time
from typing import Any

import httpx
import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.api.capture import capture_internal

logger = structlog.get_logger(__name__)

# Representative IPs for each AWS region (AWS-owned IP ranges)
# These IPs will be used for GeoIP resolution to show correct region in events
REGION_IPS = {
    "us-east-2": "18.220.0.0",  # Ohio
    "ap-northeast-2": "13.124.0.0",  # Seoul
    "sa-east-1": "18.228.0.0",  # São Paulo
    "us-west-2": "44.224.0.0",  # Oregon
    "eu-central-1": "3.120.0.0",  # Frankfurt
    "eu-west-1": "34.240.0.0",  # Ireland
}


@activity.defn
async def get_monitors_due_for_check() -> list[tuple[str, str]]:
    """
    Query database for monitors that are enabled and due for check.
    Returns list of (monitor_id, region) tuples.
    """
    from products.synthetic_monitoring.backend.models import SyntheticMonitor

    monitors = await sync_to_async(list)(
        SyntheticMonitor.objects.filter(enabled=True).select_related("team").values("id", "regions")
    )

    checks_to_run = []
    for monitor_data in monitors:
        monitor_id = str(monitor_data["id"])
        regions = monitor_data["regions"] if monitor_data["regions"] else ["us-east-1"]

        # For simplicity, we run all monitors every scheduler tick
        # In a more sophisticated implementation, we could track last_checked_at
        # and only run monitors that are actually due based on frequency_minutes
        for region in regions:
            checks_to_run.append((monitor_id, region))

    logger.info(f"Found {len(checks_to_run)} checks to run across {len(monitors)} monitors")
    return checks_to_run


@activity.defn
async def execute_http_check_via_lambda(monitor_id: str, region: str) -> None:
    """
    Execute HTTP check for a monitor by calling Lambda URL.
    Updates monitor state and emits events based on results.
    """
    from django.conf import settings

    from products.synthetic_monitoring.backend.models import SyntheticMonitor

    try:
        monitor = await sync_to_async(SyntheticMonitor.objects.select_related("team").get)(id=monitor_id)
    except SyntheticMonitor.DoesNotExist:
        logger.exception("Monitor not found", monitor_id=monitor_id)
        return

    lambda_urls = settings.SYNTHETIC_MONITORING_LAMBDA_URLS
    lambda_url = lambda_urls.get(region)
    if not lambda_url:
        logger.error(
            "Lambda URL not configured for region",
            monitor_id=monitor_id,
            region=region,
            available_regions=list(lambda_urls.keys()),
        )
        await emit_check_event(
            monitor=monitor,
            region=region,
            success=False,
            status_code=None,
            response_time_ms=0,
            error_message=f"Lambda URL not configured for region {region}",
            timing_metrics=None,
        )
        return

    # Prepare payload for Lambda
    payload = {
        "url": monitor.url,
        "method": monitor.method,
        "headers": monitor.headers or {},
        "body": monitor.body,
        "expected_status_code": monitor.expected_status_code,
        "timeout_seconds": monitor.timeout_seconds,
    }

    success = False
    status_code = None
    error_message = None
    response_time_ms = None
    timing_metrics = {}

    try:
        start_time = time.time()
        async with httpx.AsyncClient() as client:
            response = await client.post(
                lambda_url,
                json=payload,
                timeout=15.0,
            )
            invocation_time_ms = int((time.time() - start_time) * 1000)
            response.raise_for_status()

            result = response.json()
            success = result.get("success", False)
            status_code = result.get("status_code")
            response_time_ms = result.get("response_time_ms", 0)
            error_message = result.get("error_message")

            # Extract timing metrics from Lambda response
            timing_metrics = {
                "dns_ms": result.get("dns_ms"),
                "tcp_ms": result.get("tcp_ms"),
                "tls_ms": result.get("tls_ms"),
                "request_send_ms": result.get("request_send_ms"),
                "download_ms": result.get("download_ms"),
                "total_ms": result.get("total_ms"),
            }

            logger.info(
                "HTTP check completed via Lambda",
                monitor_id=monitor_id,
                url=monitor.url,
                region=region,
                success=success,
                status_code=status_code,
                response_time_ms=response_time_ms,
                lambda_invocation_ms=invocation_time_ms,
                **timing_metrics,
            )

    except httpx.HTTPStatusError as e:
        error_message = f"Lambda returned error: {e.response.status_code}"
        response_time_ms = 0
        logger.exception("Lambda HTTP error", monitor_id=monitor_id, region=region, error=str(e))

    except httpx.TimeoutException:
        error_message = "Lambda request timed out"
        response_time_ms = 0
        logger.warning("Lambda timeout", monitor_id=monitor_id, region=region)

    except Exception as e:
        error_message = f"Lambda invocation failed: {str(e)}"
        response_time_ms = 0
        logger.exception("Lambda invocation error", monitor_id=monitor_id, region=region, error=str(e))

    # Emit event to ClickHouse
    await emit_check_event(
        monitor=monitor,
        region=region,
        success=success,
        status_code=status_code,
        response_time_ms=response_time_ms,
        error_message=error_message,
        timing_metrics=timing_metrics,
    )


async def emit_check_event(
    monitor: Any,
    region: str,
    success: bool,
    status_code: int | None,
    response_time_ms: int | None,
    error_message: str | None,
    timing_metrics: dict | None = None,
) -> None:
    """Emit synthetic check event to ClickHouse"""
    try:
        properties = {
            "$synthetic_monitor_id": str(monitor.id),
            "$synthetic_monitor_name": monitor.name,
            "$synthetic_url": monitor.url,
            "$synthetic_method": monitor.method,
            "$synthetic_region": region,
            "$synthetic_success": success,
            "$synthetic_status_code": status_code,
            "$synthetic_response_time_ms": response_time_ms,
            "$synthetic_error_message": error_message,
            "$synthetic_expected_status_code": monitor.expected_status_code,
        }

        if timing_metrics:
            for key, value in timing_metrics.items():
                if value is not None:
                    properties[f"$synthetic_{key}"] = value

        # Add IP address for GeoIP resolution to match the Lambda region
        region_ip = REGION_IPS.get(region, "127.0.0.1")
        properties["$ip"] = region_ip

        await sync_to_async(capture_internal)(
            token=monitor.team.api_token,
            event_name="$synthetic_http_check",
            event_source="synthetic_monitoring",
            # Quite a stretch but we need to send something, so let's use the monitor ID to avoid creating new distinct IDs for each run
            distinct_id=f"monitor_{monitor.id}",
            timestamp=None,
            properties=properties,
        )
        logger.info("Emitted synthetic check event", monitor_id=str(monitor.id), success=success)
    except Exception as e:
        logger.exception("Failed to emit synthetic check event", monitor_id=str(monitor.id), error=str(e))
