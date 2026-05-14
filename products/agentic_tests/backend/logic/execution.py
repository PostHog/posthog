"""
Execution path for an agentic test run.

Runner contract (returned by `_run` and persisted by `execute_agentic_test`):

    { passed: bool, output: dict, error?: str, external_session_id?: str, screenshot_url?: str }

The default backend is the Python agent loop in `runner.py` (Anthropic +
Playwright + Browserbase). `_run_mock` is kept for tests/demos where we
don't want to hit a real LLM.

On failure we emit a `$agentic_test_result` event so anyone wanting Slack /
PagerDuty / etc alerts can wire a HogFunction destination filtered on that
event — no per-test config needed.
"""

import time
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.ph_client import ph_scoped_capture

from products.agentic_tests.backend.models import AgenticTest, AgenticTestRun

from .runner import AgentEvent, run_agent

logger = structlog.get_logger(__name__)


def queue_agentic_test_run(test: AgenticTest, *, source: str = AgenticTestRun.Source.MANUAL) -> AgenticTestRun:
    """
    Create a run row in RUNNING state and dispatch a celery task to finish it.

    The API returns the row immediately so the UI shows "Running" while the task
    picks it up and updates the row to passed/failed.
    """
    from products.agentic_tests.backend.tasks.tasks import run_agentic_test_run

    run = AgenticTestRun.objects.create(
        agentic_test=test,
        status=AgenticTestRun.Status.RUNNING,
        source=source,
    )
    run_id = str(run.id)
    transaction.on_commit(lambda: run_agentic_test_run.delay(run_id))
    return run


def execute_agentic_test_run(run_id: str) -> None:
    """Execute an existing running run row to completion. Called from the celery worker."""
    run = AgenticTestRun.objects.select_related("agentic_test__team").get(id=run_id)
    test = run.agentic_test

    log_entries: list[dict[str, Any]] = []
    start = time.monotonic()
    try:
        result = _run(test, run=run, log_entries=log_entries)
    except Exception as exc:  # noqa: BLE001 — surface anything as a failed run
        logger.exception("agentic_test_runner_error", test_id=str(test.id), error=str(exc))
        result = {"passed": False, "output": {}, "error": f"Runner error: {exc}"}

    duration_ms = int((time.monotonic() - start) * 1000)
    run.finished_at = timezone.now()
    run.duration_ms = duration_ms

    agent_passed = bool(result["passed"])
    assertion_results = _evaluate_assertions(test=test, run=run, agent_output=result.get("output", {}))
    assertions_passed = all(a["passed"] for a in assertion_results)
    overall_passed = agent_passed and assertions_passed

    output = dict(result.get("output", {}))
    output["assertions"] = assertion_results
    output["agent_passed"] = agent_passed

    run.output = output
    run.external_session_id = result.get("external_session_id", "")
    run.screenshot_url = result.get("screenshot_url", "")
    run.region = result.get("region", "")
    run.posthog_session_id = _lookup_posthog_session_id(team_id=test.team_id, run=run)
    run.log_entries = log_entries
    if not run.posthog_session_id:
        # Events may still be in flight through Kafka -> CH; retry after a delay so
        # the link populates without the user needing to refresh.
        from products.agentic_tests.backend.tasks.tasks import pair_posthog_session_for_run

        pair_posthog_session_for_run.apply_async(args=[str(run.id)], countdown=20)
    run.status = AgenticTestRun.Status.PASSED if overall_passed else AgenticTestRun.Status.FAILED
    if not overall_passed:
        if not agent_passed:
            run.error_message = (result.get("error") or "")[:5000]
        else:
            failed = [a for a in assertion_results if not a["passed"]]
            run.error_message = "; ".join(a.get("message", "Assertion failed") for a in failed)[:5000]
        _emit_failure_event(test=test, run=run)
    run.save()

    test.last_run_at = run.started_at
    test.save(update_fields=["last_run_at", "updated_at"])


def _evaluate_assertions(
    *, test: AgenticTest, run: AgenticTestRun, agent_output: dict[str, Any]
) -> list[dict[str, Any]]:
    """Evaluate each assertion declared on the test. Returns a list of per-assertion result dicts."""
    results: list[dict[str, Any]] = []
    for assertion in test.assertions or []:
        kind = assertion.get("type")
        try:
            if kind == "url_contains":
                value = (assertion.get("value") or "").strip()
                final_url = str(agent_output.get("final_url") or test.target_url)
                passed = bool(value) and value in final_url
                message = f"URL contains '{value}'" if passed else f"URL '{final_url}' does not contain '{value}'"
            elif kind == "event_captured":
                passed, message = _check_event_captured(
                    team_id=test.team_id,
                    event=(assertion.get("event") or "").strip(),
                    within_seconds=int(assertion.get("within_seconds") or 30),
                    started_at=run.started_at,
                )
            else:
                passed = False
                message = f"Unsupported assertion type: {kind}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("agentic_test_assertion_failed", test_id=str(test.id), kind=kind, error=str(exc))
            passed = False
            message = f"Assertion errored: {exc}"

        results.append({"type": kind, "passed": passed, "message": message, "config": assertion})
    return results


def _check_event_captured(*, team_id: int, event: str, within_seconds: int, started_at: Any) -> tuple[bool, str]:
    """Query the events table for at least one matching event in the window."""
    if not event:
        return False, "Event name is required"

    from posthog.clickhouse.client import sync_execute

    window_end = started_at + timedelta(seconds=within_seconds)
    rows = sync_execute(
        """
        SELECT count() FROM events
        WHERE team_id = %(team_id)s
          AND event = %(event)s
          AND timestamp >= %(start)s
          AND timestamp < %(end)s
        """,
        {"team_id": team_id, "event": event, "start": started_at, "end": window_end},
    )
    count = rows[0][0] if rows else 0
    if count > 0:
        return True, f"Captured {count} '{event}' event(s) within {within_seconds}s"
    return False, f"No '{event}' events captured within {within_seconds}s"


def _run(test: AgenticTest, *, run: AgenticTestRun, log_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Dispatch to the real Python agent loop or the deterministic mock based on settings.

    Every AgentEvent emitted by the runner is appended to `log_entries` (mutated in place)
    so the caller can persist them on the run row, even if the runner crashes mid-stream.
    """
    if getattr(settings, "AGENTIC_TESTS_USE_MOCK_RUNNER", False):
        return _run_mock(test)

    final: dict[str, Any] | None = None
    for event in run_agent(
        prompt=test.prompt,
        target_url=test.target_url,
        regions=list(test.regions or []),
        test_id=str(test.id),
        test_name=test.name,
        run_id=str(run.id),
    ):
        log_entries.append(_event_to_dict(event))
        if event.type == "final":
            final = event.data
    if final is None:
        return {"passed": False, "output": {}, "error": "Runner produced no final event"}
    return final


def _event_to_dict(event: AgentEvent) -> dict[str, Any]:
    """Serialize an AgentEvent for persistence, attaching a UTC timestamp."""
    d = asdict(event)
    d["ts"] = timezone.now().isoformat()
    return d


def _lookup_posthog_session_id(*, team_id: int, run: AgenticTestRun) -> str:
    """Find the PostHog session replay matching this run's user-agent tag, if any.

    The runner sets `navigator.userAgent` to include `run=<run.id>`, which the customer's
    own posthog-js captures on every event under `$user_agent`. Querying for that exact
    substring within the run's time window gives us the single session_id to link to.

    Best-effort: returns empty string if no event matched (e.g. customer's site has no
    posthog-js, or the agent didn't capture any events before the run completed).
    """
    if not run.finished_at or not run.started_at:
        return ""
    from posthog.clickhouse.client import sync_execute

    try:
        # We append `?_phag=run-<id>` to the target URL before the agent navigates, so
        # the customer's posthog-js auto-captures it into `$current_url`. Lookup is a
        # substring match on that property, plus a UA fallback for defense in depth.
        rows = sync_execute(
            """
            SELECT $session_id
            FROM events
            WHERE team_id = %(team_id)s
              AND timestamp >= %(start)s
              AND timestamp <  %(end)s
              AND $session_id != ''
              AND (
                positionUTF8(JSONExtractString(properties, '$current_url'), %(needle)s) > 0
                OR positionUTF8(JSONExtractString(properties, '$initial_current_url'), %(needle)s) > 0
                OR positionUTF8(JSONExtractString(properties, '$raw_user_agent'), %(ua_needle)s) > 0
              )
            ORDER BY timestamp ASC
            LIMIT 1
            """,
            {
                "team_id": team_id,
                "start": run.started_at,
                "end": run.finished_at + timedelta(minutes=5),
                "needle": f"_phag=run-{run.id}",
                "ua_needle": f"run={run.id}",
            },
        )
    except Exception as exc:  # noqa: BLE001 — non-fatal, just no link
        logger.warning("agentic_test_session_lookup_failed", run_id=str(run.id), error=str(exc))
        return ""
    return str(rows[0][0]) if rows and rows[0] and rows[0][0] else ""


def _run_mock(test: AgenticTest) -> dict[str, Any]:
    """Deterministic mock for tests and seeded demos. Always passes."""
    return {
        "passed": True,
        "output": {"steps_completed": 5, "evaluation": "Prompt satisfied."},
        "external_session_id": "mock-session",
    }


def _emit_failure_event(*, test: AgenticTest, run: AgenticTestRun) -> None:
    """Emit a `$agentic_test_result` event so error_tracking + logs + HogFunction destinations can pick it up."""
    try:
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=f"agentic_test:{test.id}",
                event="$agentic_test_result",
                properties={
                    "$exception_type": "AgenticTestFailure",
                    "$exception_message": run.error_message or "Agentic test failed",
                    "agentic_test_id": str(test.id),
                    "agentic_test_run_id": str(run.id),
                    "agentic_test_name": test.name,
                    "external_session_id": run.external_session_id,
                    "team_id": test.team_id,
                },
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("agentic_test_event_emit_failed", error=str(exc))
