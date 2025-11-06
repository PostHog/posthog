import os
import json
import time
from typing import Any

import httpx
import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.api.capture import capture_internal

logger = structlog.get_logger(__name__)

# Load Lambda URLs from environment variable
LAMBDA_URLS = json.loads(os.getenv("SYNTHETIC_MONITORING_LAMBDA_URLS", "{}"))


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
    from products.synthetic_monitoring.backend.models import SyntheticMonitor

    try:
        monitor = await sync_to_async(SyntheticMonitor.objects.select_related("team").get)(id=monitor_id)
    except SyntheticMonitor.DoesNotExist:
        logger.exception("Monitor not found", monitor_id=monitor_id)
        return

    lambda_url = LAMBDA_URLS.get(region)
    if not lambda_url:
        logger.error(
            "Lambda URL not configured for region",
            monitor_id=monitor_id,
            region=region,
            available_regions=list(LAMBDA_URLS.keys()),
        )
        await emit_check_event(
            monitor=monitor,
            region=region,
            success=False,
            status_code=None,
            response_time_ms=0,
            error_message=f"Lambda URL not configured for region {region}",
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

            logger.info(
                "HTTP check completed via Lambda",
                monitor_id=monitor_id,
                url=monitor.url,
                region=region,
                success=success,
                status_code=status_code,
                response_time_ms=response_time_ms,
                lambda_invocation_ms=invocation_time_ms,
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
    )


async def emit_check_event(
    monitor: Any,
    region: str,
    success: bool,
    status_code: int | None,
    response_time_ms: int | None,
    error_message: str | None,
) -> None:
    """Emit synthetic check event to ClickHouse"""
    try:
        await sync_to_async(capture_internal)(
            token=monitor.team.api_token,
            event_name="synthetic_http_check",
            event_source="synthetic_monitoring",
            distinct_id=f"monitor_{monitor.id}",
            timestamp=None,
            properties={
                "monitor_id": str(monitor.id),
                "monitor_name": monitor.name,
                "url": monitor.url,
                "method": monitor.method,
                "region": region,
                "success": success,
                "status_code": status_code,
                "response_time_ms": response_time_ms,
                "error_message": error_message,
                "expected_status_code": monitor.expected_status_code,
            },
        )
        logger.info("Emitted synthetic check event", monitor_id=str(monitor.id), success=success)
    except Exception as e:
        logger.exception("Failed to emit synthetic check event", monitor_id=str(monitor.id), error=str(e))
