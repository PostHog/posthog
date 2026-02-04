"""Slack notifications for test results using incoming webhooks."""

from typing import Any

import requests
import structlog

from .config import Config
from .results import TestSuiteResult

logger = structlog.get_logger(__name__)


def send_slack_notification(config: Config, result: TestSuiteResult) -> bool:
    """Send test results to Slack via incoming webhook.

    Args:
        config: Configuration containing the Slack webhook URL.
        result: The test suite result to report.

    Returns:
        True if notification was sent successfully, False otherwise.
        Returns True if Slack is not configured (no-op).
    """
    if not config.slack_webhook_url:
        logger.debug("Slack webhook URL not configured, skipping notification")
        return True

    blocks = _build_slack_blocks(config, result)
    payload = {"blocks": blocks}

    try:
        response = requests.post(
            config.slack_webhook_url,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        logger.info("Slack notification sent successfully")
        return True
    except requests.RequestException as e:
        logger.warning("Failed to send Slack notification", error=str(e))
        return False


def _build_slack_blocks(config: Config, result: TestSuiteResult) -> list[dict[str, Any]]:
    """Build Slack blocks for the test result notification."""
    blocks: list[dict[str, Any]] = [
        _build_header_block(result),
        _build_summary_block(result),
        {"type": "divider"},
    ]
    blocks.extend(_build_failed_tests_blocks(result))
    blocks.append({"type": "divider"})
    blocks.append(_build_context_block(config, result))
    return blocks


def _build_header_block(result: TestSuiteResult) -> dict[str, Any]:
    if result.success:
        emoji = ":white_check_mark:"
        status_text = "Successful"
    else:
        emoji = ":bomb:"
        status_text = "Unsuccessful"

    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{emoji} *{status_text} run for Ingestion Acceptance Tests*",
        },
    }


def _build_summary_block(result: TestSuiteResult) -> dict[str, Any]:
    parts = [f":white_check_mark: Passed: {result.passed_count}"]

    if result.failed_count > 0:
        parts.append(f":red_circle: *Failed*: {result.failed_count}")
    else:
        parts.append(f":red_circle: Failed: {result.failed_count}")

    if result.error_count > 0:
        parts.append(f":boom: *Error*: {result.error_count}")
    else:
        parts.append(f":boom: Error: {result.error_count}")

    return {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "        ".join(parts),
            },
        ],
    }


def _build_context_block(config: Config, result: TestSuiteResult) -> dict[str, Any]:
    return {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f":globe_with_meridians: Env: {config.api_host} |  :file_folder: Project: {config.project_id} |  :hourglass: Duration: {result.total_duration_seconds:.2f}s",
            },
        ],
    }


def _build_failed_tests_blocks(result: TestSuiteResult) -> list[dict[str, Any]]:
    failed_tests = [r for r in result.results if r.status in ("failed", "error")]
    if not failed_tests:
        return []

    blocks: list[dict[str, Any]] = []
    for test_result in failed_tests:
        emoji = ":red_circle:" if test_result.status == "failed" else ":boom:"
        error_text = test_result.error_message or "No error message"
        if len(error_text) > 200:
            error_text = error_text[:200] + "..."

        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"{emoji} *{test_result.test_name}*\n{error_text}",
                    },
                ],
            }
        )

    return blocks
