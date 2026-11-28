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
import hashlib
import datetime as dt
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Literal, Optional, TypeVar

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, QuerySet, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.aeo.backend import prompt_limit
from products.aeo.backend.catalog import own_domains
from products.aeo.backend.check_brands import BrandMatcher, catalog_identities, write_check_brands
from products.aeo.backend.engine_settings import engine_schedule
from products.aeo.backend.engines import AICreditsExhausted, CitationEngine, build_check_fields
from products.aeo.backend.facade.contracts import CitationRunSummary
from products.aeo.backend.facts import write_facts
from products.aeo.backend.models import AEOCitationCheck, AEOPrompt
from products.aeo.backend.stored_results import bump_data_version_on_commit
from products.aeo.backend.temporal.brand_sentiment import start_brand_sentiment_workflow

logger = structlog.get_logger(__name__)


def run_citation_checks(
    team: Team,
    *,
    engines: Optional[list[CitationEngine]] = None,
    weekly_engines: Optional[list[CitationEngine]] = None,
    periods: Optional[dict[str, int]] = None,
    limit: Optional[int] = None,
    record: bool = True,
    stop: Optional[threading.Event] = None,
) -> tuple[CitationRunSummary, list[dict[str, Any]]]:
    """Run every due prompt against every engine; record the results.

    Returns (summary, per-check field values). Rows are written per prompt so an
    interrupted run keeps the checks it already paid for, and a later run skips
    the prompts it covered. With record=False the engines still run (and cost
    money) but nothing is written — smoke-test mode. Setting `stop` ends the run
    after the prompt in hand and drops the queued ones.

    `engines` check every due prompt. `weekly_engines` check the prompts whose day in their period is today (see
    `period_day`), inside the same per-prompt claim: `periods` gives each one's days between checks, 7 when left
    out. All default to the project's engine settings.
    """
    if engines is None and weekly_engines is None:
        schedule = engine_schedule(team.id)
        engines, weekly_engines, periods = list(schedule.daily), list(schedule.weekly), schedule.periods
    engines = engines or []
    weekly_engines = weekly_engines or []
    if not engines and not weekly_engines:
        logger.warning("aeo_citation_run_no_engines", team_id=team.id)
        return _empty_summary(team, "no engines configured (AI_GATEWAY_URL/AI_GATEWAY_API_KEY, EXA_API_KEY)"), []

    # Without an own brand no answer can cite or mention the team, so the paid engine calls would record nothing useful.
    target_domains = own_domains(team.id)
    if not target_domains:
        logger.warning("aeo_citation_run_no_own_brand", team_id=team.id)
        return _empty_summary(
            team, "no own brand: add the project's domain as a brand with kind 'own' (POST aeo_brands) first"
        ), []

    checked_before = run_day_start(timezone.now())
    run_limit = min(
        settings.AEO_MAX_PROMPTS_PER_RUN if limit is None else limit, prompt_limit.max_active_prompts(team.id)
    )
    prompts = select_prompts(team, run_limit, checked_before=checked_before)
    if not prompts:
        if not _active_prompts(team).exists():
            logger.warning("aeo_citation_run_no_prompts", team_id=team.id)
            return _empty_summary(team, "no active prompts — run `seed_aeo_prompts` first"), []
        logger.info("aeo_citation_run_nothing_due", team_id=team.id, checked_before=checked_before.isoformat())
        return _empty_summary(
            team, f"nothing due: every active prompt was checked since {checked_before.isoformat()}"
        ), []

    run_id = str(uuid.uuid4())
    # bulk_create skips RootTeamMixin.save(), so map a child environment to its parent here, as reads do.
    canonical_team_id = team.parent_team_id or team.id
    weekly_due = _weekly_due(team, prompts, checked_before, weekly_engines, periods or {}) if weekly_engines else {}
    engines_per_prompt = {prompt.id: [*engines, *weekly_due.get(prompt.id, [])] for prompt in prompts}
    idle = [prompt.id for prompt in prompts if not engines_per_prompt[prompt.id]]
    if idle and record:
        # Only weekly engines run, and none is due for these prompts today. Claim them so later
        # dispatches of this run day do not select them again.
        with team_scope(canonical_team_id):
            AEOPrompt.objects.for_team(team.id).filter(id__in=idle).update(last_checked_at=timezone.now())
        prompts = [prompt for prompt in prompts if engines_per_prompt[prompt.id]]
    daily_names = frozenset(engine.name for engine in engines)
    checks: list[dict[str, Any]] = []
    engine_failures = 0
    rows_written = 0
    write_failures = 0

    # Engine calls are network-bound and run in worker threads. Database writes stay on
    # this thread, so the workers never open their own Django connections.
    pool = ThreadPoolExecutor(max_workers=max(1, settings.AEO_RUN_CONCURRENCY))
    futures = {
        pool.submit(_check_prompt, team, run_id, engines_per_prompt[prompt.id], target_domains, prompt): prompt
        for prompt in prompts
    }
    stopped = False
    out_of_credits = False
    done = 0
    superseded = 0
    pending: set[Future[PromptCheckResult]] = set(futures)
    try:
        while pending:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                done += 1
                try:
                    result = future.result()
                except Exception as e:
                    # One prompt's unexpected engine error must not end a run that takes hours.
                    engine_failures += len(engines_per_prompt[futures[future].id])
                    logger.exception(
                        "aeo_citation_prompt_crashed",
                        team_id=team.id,
                        prompt_id=str(futures[future].id),
                        error=str(e)[:300],
                    )
                else:
                    out_of_credits = out_of_credits or result.out_of_credits
                    engine_failures += result.failures
                    checks.extend(result.fields_per_engine)
                    if record and result.fields_per_engine:
                        outcome = _record_prompt_checks(
                            team,
                            canonical_team_id,
                            run_id,
                            result.prompt,
                            result.fields_per_engine,
                            checked_before,
                            daily_names=daily_names,
                        )
                        if outcome == "written":
                            rows_written += len(result.fields_per_engine)
                        elif outcome == "superseded":
                            superseded += 1
                        else:
                            write_failures += len(result.fields_per_engine)
                if done % 100 == 0:
                    logger.info(
                        "aeo_citation_run_progress", team_id=team.id, run_id=run_id, done=done, total=len(prompts)
                    )
            if not stopped and (out_of_credits or (stop is not None and stop.is_set())):
                # Drop the queued prompts but keep draining the ones already running: their calls are
                # paid for, and recording them keeps the next dispatch from repeating them.
                stopped = True
                logger.warning(
                    "aeo_citation_run_stopped",
                    team_id=team.id,
                    run_id=run_id,
                    done=done,
                    total=len(prompts),
                    out_of_credits=out_of_credits,
                )
                pending = _drop_queued(pool, pending)
    except BaseException:
        # A Celery time limit or a worker shutdown lands here. Drop the queued prompts so they
        # make no more paid calls whose results nobody records.
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)

    summary = CitationRunSummary(
        team_id=team.id,
        run_id=run_id,
        prompts=len(prompts),
        engines=tuple(engine.name for engine in [*engines, *weekly_engines]),
        checks=len(checks),
        engine_failures=engine_failures,
        cited=sum(1 for check in checks if check["cited"]),
        rows_written=rows_written,
        write_failures=write_failures,
        error=_stop_reason(stopped=stopped, out_of_credits=out_of_credits),
        superseded=superseded,
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
    if record and rows_written:
        start_brand_sentiment_workflow(canonical_team_id, run_id)
    return summary, checks


@frozen
class PromptCheckResult:
    """One prompt's checks across every engine, before they are written."""

    prompt: AEOPrompt
    fields_per_engine: list[dict[str, Any]]
    failures: int
    out_of_credits: bool


def _check_prompt(
    team: Team, run_id: str, engines: list[CitationEngine], target_domains: list[str], prompt: AEOPrompt
) -> PromptCheckResult:
    """Run one prompt on every engine. Runs in a worker thread, so it must not touch the database."""
    fields_per_engine: list[dict[str, Any]] = []
    failures = 0
    out_of_credits = False
    for engine in engines:
        trace_id = str(uuid.uuid4())
        try:
            check = engine.run(
                prompt.prompt,
                trace_id=trace_id,
                custom_properties={
                    "aeo_prompt_id": str(prompt.id),
                    "aeo_run_id": run_id,
                    "aeo_prompt_source": prompt.prompt_source,
                    "aeo_mode": engine.mode.value,
                    # No $ai_ prefix, so the gateway keeps this on the $ai_generation
                    # event, which lets usage attribute spend back to the checked team.
                    "team_id": str(team.id),
                },
            )
        except AICreditsExhausted:
            out_of_credits = True
            break
        if check.error is not None:
            failures += 1
            logger.warning(
                "aeo_citation_check_failed",
                team_id=team.id,
                engine=engine.name,
                prompt_id=str(prompt.id),
                error=check.error,
            )
        fields_per_engine.append(
            {
                **build_check_fields(
                    check=check,
                    run_id=run_id,
                    prompt_id=str(prompt.id),
                    prompt_text=prompt.prompt,
                    prompt_source=prompt.prompt_source,
                    prompt_hash=prompt.prompt_hash,
                    target_domains=target_domains,
                ),
                "prompt_topic": prompt.topic,
                "prompt_version": prompt.current_version,
            }
        )
    return PromptCheckResult(
        prompt=prompt, fields_per_engine=fields_per_engine, failures=failures, out_of_credits=out_of_credits
    )


def period_day(prompt_id: uuid.UUID, period: int) -> int:
    """The day, out of every `period` days, on which a prompt gets its checks from an engine on that period.

    A hash of the id, so the day is the same on every worker and across restarts, which Python's
    salted `hash()` is not. It spreads the set over the period, about a `period`th of it per day."""
    digest = hashlib.sha256(str(prompt_id).encode()).digest()
    return int.from_bytes(digest[:8], "big") % period


def weekly_day(prompt_id: uuid.UUID) -> int:
    return period_day(prompt_id, 7)


def run_period_day(run_day: dt.datetime, period: int) -> int:
    return (run_day.astimezone(dt.UTC).date().toordinal() + 6) % period


def _weekly_due(
    team: Team,
    prompts: list[AEOPrompt],
    checked_before: dt.datetime,
    weekly_engines: list[CitationEngine],
    periods: dict[str, int],
) -> dict[uuid.UUID, list[CitationEngine]]:
    """Per prompt whose weekly day is this run day, the weekly engines with no answered check since the run day began.

    The weekday is the run day's, in UTC, so it stays the same for every dispatch of that run day.
    A dispatch that resumes a killed run skips the engines it already recorded for a prompt,
    including ones recorded while every daily engine failed and so left the prompt unclaimed."""
    due_engines: dict[uuid.UUID, list[CitationEngine]] = {}
    for engine in weekly_engines:
        period = periods.get(engine.name, 7)
        today = run_period_day(checked_before, period)
        for prompt in prompts:
            if period_day(prompt.id, period) == today:
                due_engines.setdefault(prompt.id, []).append(engine)
    candidates = list(due_engines)
    if not candidates:
        return {}
    recorded = set(
        AEOCitationCheck.objects.for_team(team.id)
        .filter(
            prompt_id__in=candidates,
            engine__in=[engine.name for engine in weekly_engines],
            created_at__gte=checked_before,
            check_failed=False,
        )
        .values_list("prompt_id", "engine")
    )
    due = {
        prompt_id: [engine for engine in due_engines[prompt_id] if (prompt_id, engine.name) not in recorded]
        for prompt_id in candidates
    }
    return {prompt_id: engines for prompt_id, engines in due.items() if engines}


def _drop_queued(pool: ThreadPoolExecutor, pending: set[Future[_T]]) -> set[Future[_T]]:
    """Cancel the prompts no worker has started and return the ones still running.

    A future cancelled this way never gets the completion notice `wait` relies on, so it has to
    leave the pending set by hand or the drain would block until the task time limit."""
    pool.shutdown(wait=False, cancel_futures=True)
    return {future for future in pending if not future.cancelled()}


_T = TypeVar("_T")
_RecordOutcome = Literal["written", "superseded", "failed"]


def _record_prompt_checks(
    team: Team,
    canonical_team_id: int,
    run_id: str,
    prompt: AEOPrompt,
    fields_per_engine: list[dict[str, Any]],
    checked_before: dt.datetime,
    *,
    daily_names: frozenset[str],
) -> _RecordOutcome:
    """Claim the prompt for this run day, then write its checks. Called per prompt so a
    mid-run crash keeps the completed checks.

    The claim is a conditional update of `last_checked_at`: a run that lost its lease can still
    have this prompt in flight while the dispatch that replaced it records the same prompt, and
    whichever claims second drops its result instead of writing a duplicate."""
    # A prompt every daily engine failed on was not really checked, so leave it first in line for the
    # next run. Weekly answers count only when no daily engine runs, because the next run skips their engines.
    answered = any(
        not fields["check_failed"] and (fields["engine"] in daily_names or not daily_names)
        for fields in fields_per_engine
    )
    try:
        # The fail-closed manager refuses writes without a team scope, and none of the callers
        # (the Celery task, the management command) run inside one.
        with transaction.atomic(), team_scope(canonical_team_id):
            # Two runs recording the same prompt serialize on its row, so the checks below see each
            # other's writes. The prompt row is a quiet child row, never a hot parent.
            topic = (
                AEOPrompt.objects.for_team(team.id)
                .select_for_update()
                .filter(id=prompt.id)
                .values_list("topic", flat=True)
                .first()
            )
            locked = topic is not None
            if locked:
                # A topic edit locks this row too, so the topic read here is the one after any rename, merge or
                # removal that committed while the engines answered. The run's snapshot of the prompt is older.
                fields_per_engine = [{**fields, "prompt_topic": topic} for fields in fields_per_engine]
            if answered:
                still_due = Q(last_checked_at__isnull=True) | Q(last_checked_at__lt=checked_before)
                claimed = locked and (
                    AEOPrompt.objects.for_team(team.id)
                    .filter(still_due, id=prompt.id)
                    .update(last_checked_at=timezone.now())
                )
                if not claimed:
                    logger.warning(
                        "aeo_citation_prompt_superseded", team_id=team.id, run_id=run_id, prompt_id=str(prompt.id)
                    )
                    return "superseded"
            elif (
                AEOCitationCheck.objects.for_team(team.id)
                .filter(prompt_id=prompt.id, created_at__gte=checked_before)
                .exists()
            ):
                # Failures leave the prompt unclaimed, so a run that lost its lease could otherwise add a
                # second set of failure rows next to the replacement run's.
                logger.warning(
                    "aeo_citation_prompt_superseded", team_id=team.id, run_id=run_id, prompt_id=str(prompt.id)
                )
                return "superseded"
            weekly_names = {fields["engine"] for fields in fields_per_engine} - daily_names
            if weekly_names:
                # Another dispatch may have recorded this prompt's weekly checks after this run chose its engines.
                recorded = set(
                    AEOCitationCheck.objects.for_team(team.id)
                    .filter(
                        prompt_id=prompt.id,
                        engine__in=weekly_names,
                        created_at__gte=checked_before,
                        check_failed=False,
                    )
                    .values_list("engine", flat=True)
                )
                fields_per_engine = [fields for fields in fields_per_engine if fields["engine"] not in recorded]
            written = AEOCitationCheck.objects.bulk_create(
                [AEOCitationCheck(team_id=canonical_team_id, **fields) for fields in fields_per_engine]
            )
            write_facts(written)
            try:
                # A savepoint, so a parser bug costs the brand rows, not the checks. The resolve after
                # the run writes what this left out.
                with transaction.atomic():
                    write_check_brands(written, BrandMatcher(catalog_identities(canonical_team_id)))
            except Exception as e:
                logger.exception("aeo_check_brands_write_failed", team_id=team.id, run_id=run_id, error=str(e)[:300])
            bump_data_version_on_commit(canonical_team_id)
    except Exception as e:
        logger.exception("aeo_citation_write_failed", team_id=team.id, run_id=run_id, error=str(e)[:300])
        return "failed"
    return "written"


def run_day_start(now: dt.datetime) -> dt.datetime:
    """The most recent run-day boundary at or before `now`, in UTC."""
    boundary = now.astimezone(dt.UTC).replace(
        hour=settings.AEO_RUN_DAY_START_UTC_HOUR, minute=0, second=0, microsecond=0
    )
    return boundary if boundary <= now else boundary - dt.timedelta(days=1)


def select_prompts(team: Team, limit: int, *, checked_before: Optional[dt.datetime] = None) -> list[AEOPrompt]:
    """Pick up to `limit` due prompts, alternating between topics.

    A prompt is due when it is active, unarchived, and was never checked or was
    last checked before `checked_before` (every active prompt when None). Each
    run samples every topic: it takes one prompt per topic in turn, so a single
    large topic cannot fill the run. Within a topic, prompts never checked come
    first, then the least recently checked, so a set larger than one run rotates.
    A small topic runs out of unchecked prompts first and is then re-checked
    while larger topics still rotate.
    """
    freshness = [F("last_checked_at").asc(nulls_first=True), F("rank").desc(), F("created_at").asc()]
    due = _active_prompts(team)
    if checked_before is not None:
        due = due.filter(Q(last_checked_at__isnull=True) | Q(last_checked_at__lt=checked_before))
    by_topic: dict[str, list[AEOPrompt]] = {}
    # The round-robin never takes more than `limit` prompts from one topic, so load no more than that.
    for prompt in (
        due.annotate(position_in_topic=Window(RowNumber(), partition_by=[F("topic")], order_by=freshness))
        .filter(position_in_topic__lte=limit)
        .order_by(*freshness)
    ):
        by_topic.setdefault(prompt.topic, []).append(prompt)

    selected: list[AEOPrompt] = []
    queues = list(by_topic.values())
    position = 0
    while len(selected) < limit and any(position < len(queue) for queue in queues):
        selected.extend(queue[position] for queue in queues if position < len(queue))
        position += 1
    return selected[:limit]


def _active_prompts(team: Team) -> QuerySet[AEOPrompt]:
    return AEOPrompt.objects.for_team(team.id).filter(active=True, archived_at__isnull=True)


def _stop_reason(*, stopped: bool, out_of_credits: bool) -> str | None:
    if out_of_credits:
        return "stopped: the organization is out of AI credits"
    if stopped:
        return "stopped: the run lease was lost or a stop was requested"
    return None


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
