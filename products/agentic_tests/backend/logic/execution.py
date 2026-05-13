"""
Execution path for an agentic test run.

For now this is a deterministic mock — the browserbase integration is a teammate's
piece and will replace `_run_mock`. The expected shape from any real runner is:

    { passed: bool, output: dict, error?: str, external_session_id?: str, screenshot_url?: str }

On failure we emit a `$agentic_test_result` event so anyone wanting Slack / PagerDuty /
etc alerts can wire a HogFunction destination filtered on that event — no per-test
config needed.
"""

import time
from typing import Any

from django.utils import timezone

import structlog

from posthog.ph_client import ph_scoped_capture

from products.agentic_tests.backend.models import AgenticTest, AgenticTestRun

logger = structlog.get_logger(__name__)


def execute_agentic_test(test: AgenticTest) -> AgenticTestRun:
    """Run a single execution of an agentic test and persist the result."""
    run = AgenticTestRun.objects.create(
        agentic_test=test,
        status=AgenticTestRun.Status.RUNNING,
    )
    start = time.monotonic()

    try:
        result = _run_mock(test)
    except Exception as exc:  # noqa: BLE001 — surface anything as a failed run
        logger.exception("agentic_test_runner_error", test_id=str(test.id), error=str(exc))
        result = {"passed": False, "output": {}, "error": f"Runner error: {exc}"}

    duration_ms = int((time.monotonic() - start) * 1000)
    run.finished_at = timezone.now()
    run.duration_ms = duration_ms
    run.output = result.get("output", {})
    run.external_session_id = result.get("external_session_id", "")
    run.screenshot_url = result.get("screenshot_url", "")
    run.status = AgenticTestRun.Status.PASSED if result["passed"] else AgenticTestRun.Status.FAILED
    if not result["passed"]:
        run.error_message = (result.get("error") or "")[:5000]
        _emit_failure_event(test=test, run=run)
    run.save()

    test.last_run_at = run.started_at
    test.save(update_fields=["last_run_at", "updated_at"])
    return run


def _run_mock(test: AgenticTest) -> dict[str, Any]:
    """
    Deterministic mock so the demo works without a real browser runner.

    Always returns a passing result — failed runs in the demo come from seeded
    history (see `seed_agentic_tests_demo`), not from this code path.
    """
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
