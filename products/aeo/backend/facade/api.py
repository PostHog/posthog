"""Facade for the AEO product.

The only module other products (and core) are allowed to import for data
capabilities. Celery wiring is re-exported from facade/tasks.py.
"""

from __future__ import annotations

import datetime as dt

from django.core.exceptions import ValidationError

from posthog.models.team import Team

from products.aeo.backend import gaps
from products.aeo.backend.facade.contracts import (
    CitationGap,
    CitationRunSummary,
    Prompt,
    PromptImport,
    PromptImportResult,
    PromptNotFoundError,
)
from products.aeo.backend.models import AEOPrompt
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


def list_prompts(team_id: int, *, limit: int, offset: int) -> tuple[list[Prompt], int]:
    """One page of the team's prompt set and the total count, paged in SQL."""
    prompts = AEOPrompt.objects.for_team(team_id)
    page = prompts.order_by("topic", "-rank", "created_at", "id")[offset : offset + limit]
    return [_to_prompt(p) for p in page], prompts.count()


def get_prompt(team_id: int, prompt_id: str) -> Prompt:
    return _to_prompt(_get_prompt_row(team_id, prompt_id))


def set_prompt_active(team_id: int, prompt_id: str, active: bool) -> Prompt:
    prompt = _get_prompt_row(team_id, prompt_id)
    prompt.active = active
    prompt.save(update_fields=["active", "updated_at"])
    return _to_prompt(prompt)


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


def _to_prompt(prompt: AEOPrompt) -> Prompt:
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
    )
