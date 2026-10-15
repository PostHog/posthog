"""The AEO citation runner: execute the prompt set against every configured
answer engine and record one citation check per prompt x engine.

The record is rows in `posthog_aeo_citation_check`, exposed to HogQL as
`system.aeo_citation_checks`. Insights, the SQL editor, the query API, and MCP
all read it, and the runner is the only writer — an events-based record would
have been forgeable by anyone holding the project's public capture token.

Gateway engines additionally get a `$ai_generation` event per call (emitted by
the gateway itself) carrying cost and web-search fees. That event lands in the
gateway-key owner's project, not the checked team's, and carries the
`aeo_prompt_id` / `team_id` custom properties for attribution.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from django.conf import settings

import structlog

from posthog.models.team import Team

from products.aeo.backend.engines import CitationEngine, available_engines, build_check_fields
from products.aeo.backend.facade.contracts import CitationRunSummary
from products.aeo.backend.models import AEOCitationCheck, AEOPrompt

logger = structlog.get_logger(__name__)

DEFAULT_MAX_PROMPTS_PER_RUN = 50


def run_citation_checks(
    team: Team,
    *,
    engines: Optional[list[CitationEngine]] = None,
    limit: Optional[int] = None,
    record: bool = True,
) -> tuple[CitationRunSummary, list[dict[str, Any]]]:
    """Run every active prompt against every engine; record the results.

    Returns (summary, per-check field values). Rows are written per prompt so an
    interrupted run keeps the checks it already paid for. With record=False the
    engines still run (and cost money) but nothing is written — smoke-test mode.
    """
    engines = engines if engines is not None else available_engines()
    if not engines:
        logger.warning("aeo_citation_run_no_engines", team_id=team.id)
        return _empty_summary(team, "no engines configured (AI_GATEWAY_URL/AI_GATEWAY_API_KEY, EXA_API_KEY)"), []

    prompts = list(
        AEOPrompt.objects.for_team(team.id)
        .filter(active=True)
        .order_by("-rank", "created_at")[: DEFAULT_MAX_PROMPTS_PER_RUN if limit is None else limit]
    )
    if not prompts:
        logger.warning("aeo_citation_run_no_prompts", team_id=team.id)
        return _empty_summary(team, "no active prompts — run `seed_aeo_prompts` first"), []

    run_id = str(uuid.uuid4())
    target_domains: list[str] = settings.AEO_TARGET_DOMAINS
    checks: list[dict[str, Any]] = []
    engine_failures = 0
    rows_written = 0
    write_failures = 0

    for prompt in prompts:
        prompt_rows: list[AEOCitationCheck] = []
        for engine in engines:
            trace_id = str(uuid.uuid4())
            check = engine.run(
                prompt.prompt,
                trace_id=trace_id,
                custom_properties={
                    "aeo_prompt_id": str(prompt.id),
                    "aeo_run_id": run_id,
                    "aeo_prompt_source": prompt.prompt_source,
                    # No $ai_ prefix, so the gateway keeps this on the $ai_generation
                    # event, which lets usage attribute spend back to the checked team.
                    "team_id": str(team.id),
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
            fields = build_check_fields(
                check=check,
                run_id=run_id,
                prompt_id=str(prompt.id),
                prompt_text=prompt.prompt,
                prompt_source=prompt.prompt_source,
                prompt_hash=prompt.prompt_hash,
                target_domains=target_domains,
            )
            prompt_rows.append(AEOCitationCheck(team=team, **fields))
            checks.append(fields)

        if record and prompt_rows:
            # Write per prompt so a mid-run crash keeps the completed checks.
            try:
                AEOCitationCheck.objects.bulk_create(prompt_rows)
                rows_written += len(prompt_rows)
            except Exception as e:
                write_failures += len(prompt_rows)
                logger.exception("aeo_citation_write_failed", team_id=team.id, run_id=run_id, error=str(e)[:300])

    summary = CitationRunSummary(
        team_id=team.id,
        run_id=run_id,
        prompts=len(prompts),
        engines=tuple(engine.name for engine in engines),
        checks=len(checks),
        engine_failures=engine_failures,
        cited=sum(1 for check in checks if check["cited"]),
        rows_written=rows_written,
        write_failures=write_failures,
    )
    logger.info(
        "aeo_citation_run_complete",
        team_id=summary.team_id,
        run_id=summary.run_id,
        prompts=summary.prompts,
        checks=summary.checks,
        engine_failures=summary.engine_failures,
        cited=summary.cited,
        rows_written=summary.rows_written,
        write_failures=summary.write_failures,
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
        rows_written=0,
        write_failures=0,
        error=error,
    )
