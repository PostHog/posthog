"""The AEO citation runner: execute the prompt set against every configured
answer engine and capture one `$aeo_citation_check` event per prompt x engine.

The citation record is ordinary events — queryable in HogQL, chartable in
insights, and readable by the alerting scout — with no new storage. Gateway
engines additionally get a `$ai_generation` event per call (emitted by the
gateway itself) carrying cost and web-search fees, joinable via
`gateway_trace_id` / the `aeo_prompt_id` custom property.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from django.conf import settings

import structlog

from posthog.api.capture import CaptureInternalError, capture_batch_internal
from posthog.models.team import Team

from products.aeo.backend.engines import CitationEngine, available_engines, build_check_properties
from products.aeo.backend.facade.contracts import CitationRunSummary
from products.aeo.backend.models import AEOPrompt

logger = structlog.get_logger(__name__)

EVENT_NAME = "$aeo_citation_check"
EVENT_SOURCE = "aeo_citation_runner"
DISTINCT_ID = "aeo_citation_runner"

DEFAULT_MAX_PROMPTS_PER_RUN = 50


def run_citation_checks(
    team: Team,
    *,
    engines: Optional[list[CitationEngine]] = None,
    limit: Optional[int] = None,
    capture: bool = True,
) -> tuple[CitationRunSummary, list[dict[str, Any]]]:
    """Run every active prompt against every engine; capture the results.

    Returns (summary, per-check event properties). Events are captured per
    prompt so an interrupted run keeps the checks it already paid for. With
    capture=False the engines still run (and cost money) but nothing is
    captured — that's the smoke-test mode.
    """
    engines = engines if engines is not None else available_engines()
    if not engines:
        logger.warning("aeo_citation_run_no_engines", team_id=team.id)
        return _empty_summary(team, "no engines configured (AI_GATEWAY_URL/AI_GATEWAY_API_KEY, EXA_API_KEY)"), []

    prompts = list(
        AEOPrompt.objects.for_team(team.id)
        .filter(active=True)
        .order_by("-rank", "created_at")[: limit or DEFAULT_MAX_PROMPTS_PER_RUN]
    )
    if not prompts:
        logger.warning("aeo_citation_run_no_prompts", team_id=team.id)
        return _empty_summary(team, "no active prompts — run `seed_aeo_prompts` first"), []

    run_id = str(uuid.uuid4())
    target_domains: list[str] = settings.AEO_TARGET_DOMAINS
    checks: list[dict[str, Any]] = []
    engine_failures = 0
    events_captured = 0
    capture_failures = 0

    for prompt in prompts:
        prompt_events: list[dict[str, Any]] = []
        for engine in engines:
            trace_id = str(uuid.uuid4())
            check = engine.run(
                prompt.prompt,
                trace_id=trace_id,
                custom_properties={
                    "aeo_prompt_id": str(prompt.id),
                    "aeo_run_id": run_id,
                    "aeo_prompt_source": prompt.prompt_source,
                },
            )
            if check.error is not None:
                engine_failures += 1
                logger.warning(
                    "aeo_citation_check_failed",
                    team_id=team.id,
                    engine=engine.name,
                    prompt_id=str(prompt.id),
                    error=check.error,
                )
            properties = build_check_properties(
                check=check,
                run_id=run_id,
                prompt_id=str(prompt.id),
                prompt_text=prompt.prompt,
                prompt_source=prompt.prompt_source,
                prompt_hash=prompt.prompt_hash,
                target_domains=target_domains,
            )
            prompt_events.append({"event": EVENT_NAME, "distinct_id": DISTINCT_ID, "properties": properties})
            checks.append(properties)

        if capture and prompt_events:
            # Flush per prompt so a mid-run crash keeps the completed checks.
            try:
                result = capture_batch_internal(events=prompt_events, token=team.api_token, event_source=EVENT_SOURCE)
                result.raise_for_status()
                events_captured += len(prompt_events)
            except CaptureInternalError as e:
                capture_failures += len(prompt_events)
                logger.exception("aeo_citation_capture_failed", team_id=team.id, run_id=run_id, error=str(e)[:300])

    summary = CitationRunSummary(
        team_id=team.id,
        run_id=run_id,
        prompts=len(prompts),
        engines=tuple(engine.name for engine in engines),
        checks=len(checks),
        engine_failures=engine_failures,
        cited=sum(1 for check in checks if check["cited"]),
        events_captured=events_captured,
        capture_failures=capture_failures,
    )
    logger.info(
        "aeo_citation_run_complete",
        team_id=summary.team_id,
        run_id=summary.run_id,
        prompts=summary.prompts,
        checks=summary.checks,
        engine_failures=summary.engine_failures,
        cited=summary.cited,
        events_captured=summary.events_captured,
        capture_failures=summary.capture_failures,
    )
    return summary, checks


def _empty_summary(team: Team, error: str) -> CitationRunSummary:
    return CitationRunSummary(
        team_id=team.id,
        run_id=None,
        prompts=0,
        engines=(),
        checks=0,
        engine_failures=0,
        cited=0,
        events_captured=0,
        capture_failures=0,
        error=error,
    )
