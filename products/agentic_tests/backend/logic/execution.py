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
import threading
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


def queue_agentic_test_run(
    test: AgenticTest, *, source: str = AgenticTestRun.Source.MANUAL, region: str = ""
) -> AgenticTestRun:
    """Create a single run row pinned to one region and dispatch celery to execute it."""
    from products.agentic_tests.backend.tasks.tasks import run_agentic_test_run

    run = AgenticTestRun.objects.create(
        agentic_test=test,
        status=AgenticTestRun.Status.RUNNING,
        source=source,
        region=region,
    )
    run_id = str(run.id)
    transaction.on_commit(lambda: run_agentic_test_run.delay(run_id))
    return run


def queue_agentic_test_runs(test: AgenticTest, *, source: str = AgenticTestRun.Source.MANUAL) -> list[AgenticTestRun]:
    """
    Fan out: create one run row per configured region. If the test has no regions
    configured, a single run is created with the runner's default region.

    This is what triggers a "test execution" — every entry point (manual Run, scheduled
    beat tick, future webhook/API) calls this so users get the same multi-region behaviour
    regardless of how the test was triggered.
    """
    regions = [r for r in (test.regions or []) if r]
    if not regions:
        return [queue_agentic_test_run(test, source=source, region="")]
    return [queue_agentic_test_run(test, source=source, region=region) for region in regions]


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
    # Eager pairing: the runner reads `window.posthog.get_session_id()` directly via
    # page.evaluate right after navigation, so we usually already have the session id
    # by the time we get here — no CH query needed. Only fall back to lookup + retry
    # if the customer's posthog-js wasn't available on the page.
    eager_session_id = result.get("posthog_session_id", "")
    if eager_session_id:
        run.posthog_session_id = eager_session_id
    else:
        run.posthog_session_id = _lookup_posthog_session_id(team_id=test.team_id, run=run)
    run.log_entries = log_entries
    if not run.posthog_session_id:
        # Recording-blob-ingestion writes blobs in ~5-10s windows and the aggregating
        # MV merges on its own schedule, so session_replay_events isn't always
        # queryable immediately at run finish. Retry at 15s/60s/120s.
        from products.agentic_tests.backend.tasks.tasks import pair_posthog_session_for_run

        pair_posthog_session_for_run.apply_async(args=[str(run.id)], countdown=15)
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
    """Evaluate each assertion against the agent's specific PostHog session.

    Every assertion is scoped to `run.posthog_session_id` (set by the runner's eager
    pairing). If no session was paired (customer site has no posthog-js, or it failed to
    load), assertions return passed=False with an explicit "no session" message rather
    than silently widening the scope and risking false positives.
    """
    results: list[dict[str, Any]] = []
    for assertion in test.assertions or []:
        kind = assertion.get("type")
        try:
            if kind == "event_captured":
                passed, message = _check_event_count(
                    run=run,
                    event=(assertion.get("event") or "").strip(),
                    within_seconds=int(assertion.get("within_seconds") or 30),
                    expect_present=True,
                )
            elif kind == "event_not_captured":
                passed, message = _check_event_count(
                    run=run,
                    event=(assertion.get("event") or "").strip(),
                    within_seconds=int(assertion.get("within_seconds") or 30),
                    expect_present=False,
                )
            elif kind == "no_console_errors":
                passed, message = _check_no_console_errors(
                    run=run,
                    max_errors=int(assertion.get("max_errors") or 0),
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


def _check_event_count(
    *, run: AgenticTestRun, event: str, within_seconds: int, expect_present: bool
) -> tuple[bool, str]:
    """Count events for the agent's session, scoped by `$session_id = run.posthog_session_id`.

    `expect_present=True` -> assertion passes when count > 0 (event was captured).
    `expect_present=False` -> assertion passes when count == 0 (event NOT captured).
    """
    if not event:
        return False, "Event name is required"
    if not run.posthog_session_id:
        return False, "No PostHog session paired — this assertion needs posthog-js on the target site"

    from posthog.clickhouse.client import sync_execute

    window_end = run.started_at + timedelta(seconds=within_seconds)
    rows = sync_execute(
        """
        SELECT count()
        FROM events
        WHERE team_id = %(team_id)s
          AND $session_id = %(session_id)s
          AND event = %(event)s
          AND timestamp >= %(start)s
          AND timestamp <  %(end)s
        """,
        {
            "team_id": run.agentic_test.team_id,
            "session_id": run.posthog_session_id,
            "event": event,
            "start": run.started_at,
            "end": window_end,
        },
    )
    count = int(rows[0][0]) if rows and rows[0] else 0
    if expect_present:
        if count > 0:
            return True, f"Captured {count} '{event}' event(s)"
        return False, f"No '{event}' events captured within {within_seconds}s"
    # expect absent
    if count == 0:
        return True, f"'{event}' was not captured (as expected)"
    return False, f"Unexpected: captured {count} '{event}' event(s)"


def _check_no_console_errors(*, run: AgenticTestRun, max_errors: int = 0) -> tuple[bool, str]:
    """Verify the agent's session produced no console errors (per session_replay_events)."""
    if not run.posthog_session_id:
        return False, "No PostHog session paired — this assertion needs posthog-js on the target site"

    from posthog.clickhouse.client import sync_execute

    rows = sync_execute(
        """
        SELECT sum(console_error_count)
        FROM session_replay_events
        WHERE team_id = %(team_id)s
          AND session_id = %(session_id)s
        """,
        {"team_id": run.agentic_test.team_id, "session_id": run.posthog_session_id},
    )
    errors = int(rows[0][0] or 0) if rows and rows[0] else 0
    if errors <= max_errors:
        return True, "No console errors" if errors == 0 else f"{errors} console error(s) (<= {max_errors} allowed)"
    return False, f"{errors} console error(s) (max allowed: {max_errors})"


def _run(test: AgenticTest, *, run: AgenticTestRun, log_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Dispatch to the real Python agent loop or the deterministic mock based on settings.

    Every AgentEvent emitted by the runner is appended to `log_entries` AND flushed to
    the run row incrementally, so the UI's polling loop sees live progress (refresh-
    resilient — works even after a page reload).
    """
    if getattr(settings, "AGENTIC_TESTS_USE_MOCK_RUNNER", False):
        return _run_mock(test)

    final: dict[str, Any] | None = None
    # Pin this run to its own region (set when the row was created). If empty, the runner
    # falls back to the Browserbase default. The fan-out across regions happens at queue
    # time in `queue_agentic_test_runs`, not in the runner.
    regions = [run.region] if run.region else []
    last_flush = time.monotonic()
    eager_session_persisted = False
    for event in run_agent(
        prompt=test.prompt,
        target_url=test.target_url,
        regions=regions,
        test_id=str(test.id),
        test_name=test.name,
        run_id=str(run.id),
    ):
        log_entries.append(_event_to_dict(event))
        if event.type == "final":
            final = event.data
        # As soon as the runner publishes the eagerly-paired session id (via a `status`
        # event right after navigation), persist it to the run row so the UI's polling
        # loop can show "View replay →" within seconds of run start — not at run end.
        if not eager_session_persisted and event.type == "status":
            sid = event.data.get("posthog_session_id", "")
            if sid:
                _flush_run_field_in_background(run_id=run.id, field="posthog_session_id", value=sid)
                eager_session_persisted = True
        # Flush every ~1.5s so polling clients see progress without hammering the DB
        # on every event (a busy agent emits ~2-3 events per second).
        # NOTE: this loop is consumed inside the runner's `sync_playwright()` context,
        # which keeps an asyncio loop running on this thread. Django ORM refuses sync
        # calls from a thread with a running event loop, so we offload the write to a
        # plain daemon thread that has no loop attached.
        if time.monotonic() - last_flush > 1.5:
            _flush_log_entries_in_background(run_id=run.id, log_entries=list(log_entries))
            last_flush = time.monotonic()
    if final is None:
        return {"passed": False, "output": {}, "error": "Runner produced no final event"}
    return final


def _event_to_dict(event: AgentEvent) -> dict[str, Any]:
    """Serialize an AgentEvent for persistence, attaching a UTC timestamp."""
    d = asdict(event)
    d["ts"] = timezone.now().isoformat()
    return d


def _flush_run_field_in_background(*, run_id: Any, field: str, value: Any) -> None:
    """Persist a single field on the run row from a fresh thread (bypasses Playwright loop)."""

    def _write() -> None:
        try:
            AgenticTestRun.objects.filter(id=run_id).update(**{field: value})
        except Exception as exc:  # noqa: BLE001 — never let a flush failure crash the runner
            logger.warning("agentic_test_field_flush_failed", run_id=str(run_id), field=field, error=str(exc))

    t = threading.Thread(target=_write, daemon=True)
    t.start()
    t.join(timeout=3.0)


def _flush_log_entries_in_background(*, run_id: Any, log_entries: list[dict[str, Any]]) -> None:
    """Persist `log_entries` to the run row from a fresh thread.

    Django refuses sync ORM calls from any thread with an active asyncio loop, and the
    caller of this function runs inside `sync_playwright()` which keeps a loop running.
    A plain Thread without a loop bypasses that check. We `.join` with a short timeout
    so we don't hang the runner if the DB is briefly slow; if it times out the next
    flush will overwrite anyway.
    """

    def _write() -> None:
        try:
            AgenticTestRun.objects.filter(id=run_id).update(log_entries=log_entries)
        except Exception as exc:  # noqa: BLE001 — never let a flush failure crash the runner
            logger.warning("agentic_test_log_flush_failed", run_id=str(run_id), error=str(exc))

    t = threading.Thread(target=_write, daemon=True)
    t.start()
    t.join(timeout=3.0)


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
        # Primary: query `session_replay_events` directly. The recordings ingestion
        # path is independent of the events/person-processing pipeline, so this lands
        # faster and more reliably than searching `events.properties.$current_url`.
        # We match on `first_url` — the landing URL — which always contains our
        # `?_phag=run-<id>` tag since the runner appends it before the agent navigates.
        rows = sync_execute(
            """
            SELECT session_id
            FROM session_replay_events
            WHERE team_id = %(team_id)s
              AND min_first_timestamp >= %(start)s
              AND min_first_timestamp <  %(end)s
            GROUP BY session_id, team_id
            HAVING positionUTF8(coalesce(argMinMerge(first_url), ''), %(needle)s) > 0
            ORDER BY min(min_first_timestamp) ASC
            LIMIT 1
            """,
            {
                "team_id": team_id,
                "start": run.started_at,
                "end": run.finished_at + timedelta(minutes=5),
                "needle": f"_phag=run-{run.id}",
            },
        )
        if not rows:
            # Fallback: try the events table by `$current_url` + UA. Slower path but
            # covers cases where recording metadata isn't populated yet (e.g. session
            # was too short to produce a recording row).
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
