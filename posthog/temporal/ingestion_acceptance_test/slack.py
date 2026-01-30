"""Slack notifications for test results using incoming webhooks."""

import logging
from typing import Any

import requests

from .config import Config
from .results import TestSuiteResult

logger = logging.getLogger(__name__)


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
        logger.warning("Failed to send Slack notification: %s", e)
        return False


def _build_slack_blocks(config: Config, result: TestSuiteResult) -> list[dict[str, Any]]:
    """Build Slack blocks for the test result notification."""
    blocks: list[dict[str, Any]] = [
        _build_header_block(result),
        _build_summary_block(result),
        _build_context_block(config, result),
        {"type": "divider"},
    ]
    blocks.extend(_build_failed_tests_blocks(result))
    blocks.extend(_build_passed_tests_blocks(result))
    return blocks


def _build_header_block(result: TestSuiteResult) -> dict[str, Any]:
    status_emoji = ":white_check_mark:" if result.success else ":x:"
    status_text = "Passed" if result.success else "Failed"
    return {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"{status_emoji} Ingestion Acceptance Tests: {status_text}",
            "emoji": True,
        },
    }


def _build_summary_block(result: TestSuiteResult) -> dict[str, Any]:
    return {
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*Total:*\n{result.total_count}"},
            {"type": "mrkdwn", "text": f"*Passed:*\n:white_check_mark: {result.passed_count}"},
            {"type": "mrkdwn", "text": f"*Failed:*\n:x: {result.failed_count}"},
            {"type": "mrkdwn", "text": f"*Errors:*\n:boom: {result.error_count}"},
        ],
    }


def _build_context_block(config: Config, result: TestSuiteResult) -> dict[str, Any]:
    return {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f":globe_with_meridians: *Environment:* {config.api_host} | :file_folder: *Project:* {config.project_id} | :clock1: *Duration:* {result.total_duration_seconds:.2f}s",
            },
        ],
    }


def _build_failed_tests_blocks(result: TestSuiteResult) -> list[dict[str, Any]]:
    failed_tests = [r for r in result.results if r.status in ("failed", "error")]
    if not failed_tests:
        return []

    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*:rotating_light: Failed Tests:*"}}
    ]

    for test_result in failed_tests:
        emoji = ":x:" if test_result.status == "failed" else ":boom:"
        error_text = test_result.error_message or "No error message"
        if len(error_text) > 200:
            error_text = error_text[:200] + "..."

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *{test_result.test_name}*\n`{test_result.test_file}`\n```{error_text}```",
                },
            }
        )

    return blocks


def _build_passed_tests_blocks(result: TestSuiteResult) -> list[dict[str, Any]]:
    passed_tests = [r for r in result.results if r.status == "passed"]
    if not passed_tests:
        return []

    passed_names = ", ".join([f"`{t.test_name}`" for t in passed_tests])
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*:white_check_mark: Passed:* {passed_names}",
            },
        }
    ]
