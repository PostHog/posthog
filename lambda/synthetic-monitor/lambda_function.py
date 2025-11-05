"""
AWS Lambda function for PostHog Synthetic Monitoring HTTP checks.

This function performs HTTP health checks and returns timing and status information.
Deploy this function to multiple AWS regions for true multi-region monitoring.

Environment Variables:
    - POSTHOG_API_KEY (optional): For authenticating callbacks to PostHog
"""

import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Execute an HTTP check and return results.

    Expected event structure:
    {
        "url": "https://example.com",
        "method": "GET",
        "headers": {"Authorization": "Bearer token"},  // optional
        "body": "request body",  // optional
        "expected_status_code": 200,
        "timeout_seconds": 30,
        "monitor_id": "uuid",
        "monitor_name": "My Monitor"
    }

    Returns:
    {
        "success": true,
        "status_code": 200,
        "response_time_ms": 234,
        "error_message": null,
        "region": "us-east-1",
        "timestamp": "2025-11-05T20:30:00Z"
    }
    """
    # Extract parameters
    url = event.get("url")
    method = event.get("method", "GET")
    headers = event.get("headers", {})
    body = event.get("body")
    expected_status_code = event.get("expected_status_code", 200)
    timeout_seconds = event.get("timeout_seconds", 30)
    monitor_id = event.get("monitor_id")
    monitor_name = event.get("monitor_name", "Unknown Monitor")

    # Validate required parameters
    if not url:
        return {
            "success": False,
            "error_message": "Missing required parameter: url",
            "status_code": None,
            "response_time_ms": 0,
        }

    # Get region from Lambda context
    region = context.invoked_function_arn.split(":")[3] if context else "unknown"

    # Prepare request
    req = urllib.request.Request(url, method=method)

    # Add headers
    for key, value in headers.items():
        req.add_header(key, value)

    # Add body if present
    if body and method in ["POST", "PUT", "PATCH"]:
        if isinstance(body, str):
            req.data = body.encode("utf-8")
        else:
            req.data = json.dumps(body).encode("utf-8")
            req.add_header("Content-Type", "application/json")

    # Execute HTTP request
    start_time = time.time()
    success = False
    status_code = None
    error_message = None
    response_time_ms = 0

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            status_code = response.status
            response_time_ms = int((time.time() - start_time) * 1000)
            success = status_code == expected_status_code

    except urllib.error.HTTPError as e:
        status_code = e.code
        response_time_ms = int((time.time() - start_time) * 1000)
        success = status_code == expected_status_code
        if not success:
            error_message = f"HTTP {status_code}: {e.reason}"

    except urllib.error.URLError as e:
        response_time_ms = int((time.time() - start_time) * 1000)
        error_message = f"URL Error: {str(e.reason)}"

    except TimeoutError:
        response_time_ms = timeout_seconds * 1000
        error_message = f"Request timed out after {timeout_seconds} seconds"

    except Exception as e:
        response_time_ms = int((time.time() - start_time) * 1000)
        error_message = f"Unexpected error: {str(e)}"

    # Build response
    result = {
        "success": success,
        "status_code": status_code,
        "response_time_ms": response_time_ms,
        "error_message": error_message,
        "region": region,
        "timestamp": datetime.now(UTC).isoformat(),
        "monitor_id": monitor_id,
        "monitor_name": monitor_name,
        "url": url,
        "method": method,
        "expected_status_code": expected_status_code,
    }

    return result
