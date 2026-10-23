"""Facade for the AEO product.

The only module other products (and core) are allowed to import for data
capabilities. Celery wiring is re-exported from facade/tasks.py.
"""

from __future__ import annotations

import uuid
import datetime as dt
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db.models import Count

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team

from products.aeo.backend import gaps
from products.aeo.backend.config import resolve_config, store_config
from products.aeo.backend.facade.contracts import (
    AEOConfig,
    CitationGap,
    CitationRunSummary,
    Prompt,
    PromptEngineCheck,
    PromptImport,
    PromptImportResult,
    PromptNotFoundError,
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


def get_config(team_id: int) -> AEOConfig:
    """The team's brand and competitor config, or the instance defaults when the
    team has none."""
    return resolve_config(resolve_effective_team_id(team_id))


def update_config(team_id: int, config: AEOConfig) -> AEOConfig:
    """Replace the team's brand and competitor config. Later runs read it; rows
    already written keep the detection they ran with.

    Empty `brand_names` derive from the target domains. Raises `AEOConfigError`
    when the config would turn detection off: no target domain, a domain that is
    not a bare hostname with a public suffix, or a name shorter than two characters."""
    return store_config(team_id, config)


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
