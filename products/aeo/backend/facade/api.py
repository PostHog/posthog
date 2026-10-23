"""Facade for the AEO product.

The only module other products (and core) are allowed to import for data
capabilities. Celery wiring is re-exported from facade/tasks.py.
"""

from __future__ import annotations

import uuid
import datetime as dt
from collections import defaultdict
from typing import Any
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db.models import Count, Max, Min, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from posthog.models.team import Team

from products.aeo.backend import gaps
from products.aeo.backend.facade.contracts import (
    CitationGap,
    CitationRunSummary,
    Prompt,
    PromptCheck,
    PromptDailyEngineStats,
    PromptEngineCheck,
    PromptEngineStats,
    PromptImport,
    PromptImportResult,
    PromptNotFoundError,
    PromptStats,
    PromptTopic,
)
from products.aeo.backend.models import AEOCitationCheck, AEOPrompt
from products.aeo.backend.runner import run_citation_checks
from products.aeo.backend.seeding import PromptCandidate, upsert_prompts


def run_citation_checks_for_team(team_id: int) -> CitationRunSummary:
    """Run the team's active prompt set against every configured answer engine
    and record one citation check per prompt x engine."""
    team = Team.objects.get(id=team_id)
    summary, _ = run_citation_checks(team)
    return summary


def list_citation_gaps(team_id: int, *, since: dt.datetime) -> list[CitationGap]:
    return gaps.list_citation_gaps(team_id, since=since)


def list_prompts(
    team_id: int, *, limit: int, offset: int, topic: str | None = None, active: bool | None = None
) -> tuple[list[Prompt], int]:
    """One page of the team's prompt set and the total count, paged in SQL.
    A topic of "" selects the prompts that have no topic."""
    prompts = AEOPrompt.objects.for_team(team_id)
    if topic is not None:
        prompts = prompts.filter(topic=topic)
    if active is not None:
        prompts = prompts.filter(active=active)
    page = list(prompts.order_by("topic", "-rank", "created_at", "id")[offset : offset + limit])
    latest_checks = _latest_checks(team_id, [prompt.id for prompt in page])
    return [_to_prompt(prompt, latest_checks.get(prompt.id, ())) for prompt in page], prompts.count()


def list_prompt_topics(team_id: int) -> list[PromptTopic]:
    rows = AEOPrompt.objects.for_team(team_id).values("topic").annotate(prompts=Count("id")).order_by("topic")
    return [PromptTopic(topic=row["topic"], prompts=row["prompts"]) for row in rows]


def get_prompt(team_id: int, prompt_id: str) -> Prompt:
    return _with_latest_checks(team_id, _get_prompt_row(team_id, prompt_id))


def set_prompt_active(team_id: int, prompt_id: str, active: bool) -> Prompt:
    prompt = _get_prompt_row(team_id, prompt_id)
    prompt.active = active
    prompt.save(update_fields=["active", "updated_at"])
    return _with_latest_checks(team_id, prompt)


def list_prompt_checks(
    team_id: int, prompt_id: str, *, limit: int, offset: int, engine: str | None = None
) -> tuple[list[PromptCheck], int]:
    """One page of a prompt's check history, newest first, and the total count."""
    prompt = _get_prompt_row(team_id, prompt_id)
    checks = AEOCitationCheck.objects.for_team(team_id).filter(prompt_id=prompt.id)
    if engine is not None:
        checks = checks.filter(engine=engine)
    page = checks.order_by("-created_at", "-id").values(*_CHECK_FIELDS)[offset : offset + limit]
    return [_to_prompt_check(row) for row in page], checks.count()


def get_prompt_stats(team_id: int, prompt_id: str, *, timezone_name: str, days: int) -> PromptStats:
    """Totals per engine over the prompt's whole history, plus per-day counts for the last `days` days
    in the team's timezone."""
    prompt = _get_prompt_row(team_id, prompt_id)
    checks = AEOCitationCheck.objects.for_team(team_id).filter(prompt_id=prompt.id)
    counts = {
        "checks": Count("id"),
        "cited": Count("id", filter=Q(cited=True)),
        "failed": Count("id", filter=Q(check_failed=True)),
    }

    engines = tuple(
        PromptEngineStats(
            engine=row["engine"],
            checks=row["checks"],
            cited=row["cited"],
            failed=row["failed"],
            first_checked_at=row["first_checked_at"],
            last_checked_at=row["last_checked_at"],
        )
        for row in checks.values("engine")
        .annotate(**counts, first_checked_at=Min("created_at"), last_checked_at=Max("created_at"))
        .order_by("engine")
    )

    tz = ZoneInfo(timezone_name)
    daily_to = timezone.now().astimezone(tz).date()
    daily_from = daily_to - dt.timedelta(days=days - 1)
    window_start = dt.datetime.combine(daily_from, dt.time.min, tzinfo=tz)
    daily = tuple(
        PromptDailyEngineStats(
            date=row["date"], engine=row["engine"], checks=row["checks"], cited=row["cited"], failed=row["failed"]
        )
        for row in checks.filter(created_at__gte=window_start)
        .annotate(date=TruncDate("created_at", tzinfo=tz))
        .values("date", "engine")
        .annotate(**counts)
        .order_by("date", "engine")
    )

    return PromptStats(
        total_checks=sum(engine.checks for engine in engines),
        engines=engines,
        daily_from=daily_from,
        daily_to=daily_to,
        daily=daily,
    )


def import_prompts(team_id: int, prompts: list[PromptImport]) -> PromptImportResult:
    """Add prompts to the team's set, or update the topic and evidence of
    prompts that already exist. Existing prompts keep their active state."""
    team = Team.objects.get(id=team_id)
    candidates = [
        PromptCandidate(
            text=item.prompt,
            source=AEOPrompt.Source.IMPORTED,
            topic=item.topic,
            evidence={"via": "api"}
            | ({"external_visibility": item.external_visibility} if item.external_visibility is not None else {}),
        )
        for item in prompts
    ]
    result = upsert_prompts(team, candidates)
    return PromptImportResult(created=result["created"], updated=result["updated"], skipped=result["skipped"])


def _get_prompt_row(team_id: int, prompt_id: str) -> AEOPrompt:
    try:
        return AEOPrompt.objects.for_team(team_id).get(id=prompt_id)
    except (AEOPrompt.DoesNotExist, ValueError, ValidationError) as error:
        raise PromptNotFoundError(prompt_id) from error


_CHECK_FIELDS = (
    "id",
    "run_id",
    "engine",
    "model",
    "created_at",
    "cited",
    "check_failed",
    "error",
    "cited_urls",
    "target_urls",
    "target_best_position",
    "top_cited_domains",
    "search_queries",
    "answer_text",
)


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


def _to_prompt_check(row: dict[str, Any]) -> PromptCheck:
    return PromptCheck(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        engine=row["engine"],
        model=row["model"],
        created_at=row["created_at"],
        cited=row["cited"],
        check_failed=row["check_failed"],
        error=row["error"],
        cited_urls=_strings(row["cited_urls"]),
        target_urls=_strings(row["target_urls"]),
        target_best_position=row["target_best_position"],
        top_cited_domains=_strings(row["top_cited_domains"]),
        search_queries=_strings(row["search_queries"]),
        answer_text=row["answer_text"],
    )


def _latest_checks(team_id: int, prompt_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[PromptEngineCheck, ...]]:
    if not prompt_ids:
        return {}
    rows = (
        AEOCitationCheck.objects.for_team(team_id)
        .filter(prompt_id__in=prompt_ids)
        .order_by("prompt_id", "engine", "-created_at")
        .distinct("prompt_id", "engine")
        .values("prompt_id", "engine", "cited", "check_failed", "created_at")
    )
    checks: dict[uuid.UUID, list[PromptEngineCheck]] = defaultdict(list)
    for row in rows:
        checks[row["prompt_id"]].append(
            PromptEngineCheck(
                engine=row["engine"],
                cited=row["cited"],
                check_failed=row["check_failed"],
                checked_at=row["created_at"],
            )
        )
    return {prompt_id: tuple(engine_checks) for prompt_id, engine_checks in checks.items()}


def _with_latest_checks(team_id: int, prompt: AEOPrompt) -> Prompt:
    return _to_prompt(prompt, _latest_checks(team_id, [prompt.id]).get(prompt.id, ()))


def _to_prompt(prompt: AEOPrompt, latest_checks: tuple[PromptEngineCheck, ...]) -> Prompt:
    visibility = (prompt.evidence or {}).get("external_visibility")
    return Prompt(
        id=str(prompt.id),
        prompt=prompt.prompt,
        topic=prompt.topic,
        prompt_source=prompt.prompt_source,
        rank=prompt.rank,
        active=prompt.active,
        last_checked_at=prompt.last_checked_at,
        external_visibility=float(visibility) if isinstance(visibility, int | float) else None,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
        latest_checks=latest_checks,
    )
