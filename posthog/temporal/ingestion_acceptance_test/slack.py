"""Slack notifications for test results using incoming webhooks.

The failure message is shaped so an on-call engineer or SherlockHog can start
an investigation from it alone: a failure class per test, the events the test
sent (uuid, distinct_id), `Environment:` / `Severity:` metadata lines, and
links to the Temporal run, the worker logs in Loki, and the runbook.
"""

import json
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import requests
import structlog

from posthog.dataclasses import frozen

from .config import Config
from .results import FailureClass, TestResult, TestSuiteResult, classify_failure
from .runner import RunningTestSnapshot

logger = structlog.get_logger(__name__)

TEMPORAL_WORKER_APP = "temporal-worker-general-purpose"

# Slack Block Kit limits: 50 blocks per message, 3000 characters of section
# text, 10 elements per context block. Context text has no documented cap;
# 2000 is a safe ceiling.
MAX_BLOCKS = 50
MAX_SECTION_TEXT_CHARS = 3000
MAX_CONTEXT_TEXT_CHARS = 2000
MAX_ERROR_MESSAGE_CHARS = 700
MAX_CAPTURED_EVENTS_LISTED = 6

# Ordered from "harness or infra problem" to "ingestion lost data" so the
# suite-level class reflects the most serious failure present.
_FAILURE_CLASS_SEVERITY: tuple[FailureClass, ...] = (
    "connection_error",
    "error",
    "assertion",
    "person_missing",
    "event_missing",
)

_FAILURE_CLASS_LABELS: dict[FailureClass, str] = {
    "connection_error": "connection error (test could not reach ClickHouse or the API)",
    "error": "unexpected error in the test",
    "assertion": "assertion failed on data that was found",
    "person_missing": "person never appeared in ClickHouse",
    "event_missing": "event never appeared in ClickHouse",
}


@frozen
class RunContext:
    """Identifiers of the Temporal run that produced the notification."""

    workflow_id: str
    workflow_run_id: str
    namespace: str
    temporal_ui_host: str

    @property
    def url(self) -> str:
        return f"{self.temporal_ui_host.rstrip('/')}/namespaces/{self.namespace}/workflows/{self.workflow_id}/{self.workflow_run_id}/history"


def send_slack_notification(config: Config, result: TestSuiteResult, run_context: RunContext | None = None) -> bool:
    """Send test results to Slack via incoming webhook.

    Only sends notifications when there are failures or errors. Successful runs
    are not reported to avoid noise.

    Args:
        config: Configuration containing the Slack webhook URL.
        result: The test suite result to report.
        run_context: The Temporal run, when known, for the run link.

    Returns:
        True if notification was sent successfully or skipped, False on send failure.
    """
    if not config.slack_webhook_url:
        logger.debug("Slack webhook URL not configured, skipping notification")
        return True

    if result.success:
        logger.debug("All tests passed, skipping Slack notification")
        return True

    blocks = _build_slack_blocks(config, result, run_context)
    return _post(config.slack_webhook_url, blocks, "Slack notification")


def send_slack_timeout_notification(
    config: Config,
    running_tests: list[RunningTestSnapshot] | None = None,
    run_context: RunContext | None = None,
) -> bool:
    """Send a timeout notification to Slack via incoming webhook.

    Args:
        config: Configuration containing the Slack webhook URL.
        running_tests: List of RunningTestSnapshot with test names and their pending
            poll descriptions (what each test was waiting for in ClickHouse).
        run_context: The Temporal run, when known, for the run link.

    Returns:
        True if notification was sent successfully or skipped, False on send failure.
    """
    if not config.slack_webhook_url:
        logger.debug("Slack webhook URL not configured, skipping timeout notification")
        return True

    blocks: list[dict[str, Any]] = [
        _section(f":hourglass: *Ingestion Acceptance Tests Timed Out in {config.lane} lane*"),
        _context(
            f":traffic_light: Lane: {config.lane} | "
            f":globe_with_meridians: Env: {config.api_host} | "
            f":file_folder: Team: {config.team_id} | "
            f":stopwatch: Timeout: {config.activity_timeout_seconds}s | "
            f":key: Token: `{config.project_api_key[:10]}...`"
        ),
    ]

    if running_tests:
        lines = []
        for info in running_tests:
            line = f"• {info.name}"
            if info.pending_poll:
                line += f" — waiting for: {info.pending_poll}"
            lines.append(line)
        blocks.append(_section(f":red_circle: *Still running ({len(running_tests)}):*\n" + "\n".join(lines)))

    timeout_class = _timeout_failure_class(running_tests or [])
    blocks.append(_metadata_section(config, failure_class=timeout_class, severity=_severity(timeout_class)))
    now = datetime.now().astimezone()
    blocks.append(
        _links_context(
            config,
            run_context,
            log_start=now - timedelta(seconds=config.activity_timeout_seconds + 300),
            log_end=now + timedelta(minutes=5),
        )
    )

    return _post(config.slack_webhook_url, blocks, "Slack timeout notification")


def _post(webhook_url: str, blocks: list[dict[str, Any]], what: str) -> bool:
    blocks = _fit_slack_limits(blocks)
    try:
        response = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
        response.raise_for_status()
        logger.info(f"{what} sent successfully")
        return True
    except requests.RequestException as e:
        logger.warning(f"Failed to send {what}", error=str(e))
        return False


def _fit_slack_limits(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trim a block list so Slack accepts it, keeping the header and the links footer."""
    if len(blocks) > MAX_BLOCKS:
        dropped = len(blocks) - (MAX_BLOCKS - 1)
        blocks = [
            *blocks[: MAX_BLOCKS - 2],
            _section(f"... {dropped} more block(s) not shown; see the Temporal run result for every test."),
            *blocks[-1:],
        ]
    fitted = []
    for block in blocks:
        if block.get("type") == "section":
            block = _section(_truncate(block["text"]["text"], MAX_SECTION_TEXT_CHARS))
        elif block.get("type") == "context":
            block = _context(_truncate(block["elements"][0]["text"], MAX_CONTEXT_TEXT_CHARS))
        fitted.append(block)
    return fitted


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _build_slack_blocks(
    config: Config, result: TestSuiteResult, run_context: RunContext | None
) -> list[dict[str, Any]]:
    failed = result.failed_results
    suite_class = _suite_failure_class(failed)
    end = _parse_timestamp(result.timestamp)
    start = end - timedelta(seconds=result.total_duration_seconds)

    blocks: list[dict[str, Any]] = [
        _build_header_block(config),
        _build_summary_block(result),
        {"type": "divider"},
    ]
    blocks.extend(_build_failed_test_block(r) for r in failed)
    blocks.append({"type": "divider"})
    blocks.append(_metadata_section(config, failure_class=suite_class, severity=_severity(suite_class)))
    blocks.append(
        _links_context(
            config,
            run_context,
            log_start=start - timedelta(minutes=5),
            log_end=end + timedelta(minutes=5),
            duration_seconds=result.total_duration_seconds,
        )
    )
    return blocks


def _build_header_block(config: Config) -> dict[str, Any]:
    # Only called when there are failures (send_slack_notification returns early on success)
    return _section(f":bomb: *Unsuccessful run in {config.lane} lane for Ingestion Acceptance Tests*")


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

    return _context("        ".join(parts))


def _build_failed_test_block(test_result: TestResult) -> dict[str, Any]:
    emoji = ":red_circle:" if test_result.status == "failed" else ":boom:"
    failure_class = classify_failure(test_result) or "error"
    error_text = test_result.error_message or "No error message"
    if len(error_text) > MAX_ERROR_MESSAGE_CHARS:
        error_text = error_text[:MAX_ERROR_MESSAGE_CHARS] + "..."
    error_type = test_result.error_type

    lines = [
        f"{emoji} *{test_result.test_file}*",
        f"Failure class: `{failure_class}` ({_FAILURE_CLASS_LABELS[failure_class]})",
        f"Error: {error_type + ': ' if error_type else ''}{error_text}",
    ]
    if test_result.captured_events:
        lines.append("Events sent by this test:")
        for ref in test_result.captured_events[:MAX_CAPTURED_EVENTS_LISTED]:
            lines.append(f"• `{ref.event}` uuid `{ref.uuid}` distinct_id `{ref.distinct_id}`")
        hidden = len(test_result.captured_events) - MAX_CAPTURED_EVENTS_LISTED
        if hidden > 0:
            lines.append(f"• ... and {hidden} more (see the Temporal run result)")
    return _section("\n".join(lines))


def _metadata_section(config: Config, failure_class: FailureClass, severity: str) -> dict[str, Any]:
    # One `Key: value` per line. Alert tooling (SherlockHog's alert parser) keys
    # on lines that start with Environment / Severity / Team.
    lines = [
        f"Environment: {config.environment_name}",
        f"Severity: {severity}",
        "Team: ingestion",
        f"Lane: {config.lane}",
        f"Project: {config.team_id}",
        f"Failure class: {failure_class}",
    ]
    return _section("\n".join(lines))


def _links_context(
    config: Config,
    run_context: RunContext | None,
    log_start: datetime,
    log_end: datetime,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    parts = [
        f":traffic_light: Lane: {config.lane}",
        f":globe_with_meridians: Env: {config.api_host}",
        f":file_folder: Team: {config.team_id}",
    ]
    if duration_seconds is not None:
        parts.append(f":hourglass: Duration: {duration_seconds:.2f}s")

    links = []
    if run_context:
        links.append(f"<{run_context.url}|Temporal run>")
    loki_url = _loki_explore_url(config, log_start, log_end)
    if loki_url:
        links.append(f"<{loki_url}|Worker logs (Loki)>")
    if config.runbook_url:
        links.append(f"<{config.runbook_url}|Runbook>")
    if links:
        parts.append(":link: " + " · ".join(links))
    return _context(" | ".join(parts))


def _loki_explore_url(config: Config, start: datetime, end: datetime) -> str | None:
    grafana = config.grafana_base_url
    if not grafana:
        return None
    logql = f'{{app="{TEMPORAL_WORKER_APP}"}} |= "ingestion_acceptance_test" | json'
    state = {
        "datasource": config.loki_datasource_uid,
        "queries": [{"refId": "A", "datasource": {"type": "loki", "uid": config.loki_datasource_uid}, "expr": logql}],
        "range": {"from": str(int(start.timestamp() * 1000)), "to": str(int(end.timestamp() * 1000))},
    }
    return f"{grafana}/explore?left={quote(json.dumps(state, separators=(',', ':')), safe='')}"


def _timeout_failure_class(running_tests: list[RunningTestSnapshot]) -> FailureClass:
    """Classify an activity timeout by what the still-running tests were waiting for.

    A test still polling for an event or a person when the budget runs out is
    the same failure as its assertion timing out. No pending poll means the
    harness itself was stuck.
    """
    pending = [t.pending_poll for t in running_tests if t.pending_poll]
    if any(p.startswith("event") for p in pending):
        return "event_missing"
    if any(p.startswith("person") for p in pending):
        return "person_missing"
    return "error"


def _suite_failure_class(failed: list[TestResult]) -> FailureClass:
    classes = {classify_failure(r) or "error" for r in failed}
    for candidate in reversed(_FAILURE_CLASS_SEVERITY):
        if candidate in classes:
            return candidate
    return "error"


def _severity(failure_class: FailureClass) -> str:
    return "warning" if failure_class in ("connection_error", "error") else "critical"


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.astimezone()


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}
