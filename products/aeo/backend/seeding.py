"""Prompt seeding for the AEO citation-tracking POC.

The prompt set is a hand-written control set or a CSV import (for example an
existing AEO tool's prompt export), both of which a person writes and reviews
before it runs.

Deriving prompts from first-party data — signup free-text, AI-landed pages,
AI-crawled paths, search-console queries — is deliberately not here. Those
sources carry text a visitor supplied into a live engine call, so they need the
prompt-injection handling the rest of our AI tooling has before they earn a
place in the pipeline.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import field
from typing import Any

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.aeo.backend.engines import MAX_PROMPT_LENGTH
from products.aeo.backend.facade.contracts import PROMPT_TOPIC_MAX_LENGTH
from products.aeo.backend.models import AEOPrompt, AEOPromptVersion

logger = structlog.get_logger(__name__)


@frozen
class PromptCandidate:
    text: str
    source: str
    topic: str = ""
    rank: float = 0
    evidence: dict[str, Any] = field(default_factory=dict)


def normalize_prompt(text: str) -> str:
    return " ".join(text.strip().split())


def prompt_hash(text: str) -> str:
    return hashlib.sha256(normalize_prompt(text).lower().encode("utf-8")).hexdigest()


def import_prompts_csv(path: str, *, source: str = AEOPrompt.Source.IMPORTED) -> list[PromptCandidate]:
    """Import prompts from a CSV — either a file with a `prompt` header column
    (and an optional `topic` column), or a headerless file with one prompt per line."""
    with open(path, newline="") as f:
        first_row = next(csv.reader(f), None)
        f.seek(0)
        has_header = first_row is not None and any(cell.strip().lower() == "prompt" for cell in first_row)
        rows: list[tuple[str, str]] = []
        if has_header:
            for row in csv.DictReader(f):
                cells = {key.strip().lower(): (value or "").strip() for key, value in row.items() if key}
                if cells.get("prompt"):
                    rows.append((cells["prompt"], cells.get("topic", "")))
        else:
            for line in f:
                text = line.strip().strip('"')
                if text:
                    rows.append((text, ""))
    return [PromptCandidate(text=text, source=source, topic=topic, evidence={"file": path}) for text, topic in rows]


def upsert_prompts(team: Team, candidates: list[PromptCandidate]) -> dict[str, int]:
    """Write the candidates to the prompt set, skipping empty, oversized and archived ones.

    MAX_PROMPT_LENGTH is a payload-size guard, not a security control: it keeps a
    single prompt from bloating every check event it appears on, and it matches
    what a check event records for prompt_text.
    """
    # bulk_create skips RootTeamMixin.save(), so map a child environment to its parent here, as reads do.
    team_id = team.parent_team_id or team.id
    skipped = 0
    rows: dict[str, AEOPrompt] = {}
    candidate_keys: list[str] = []
    now = timezone.now()
    for candidate in candidates:
        text = normalize_prompt(candidate.text)
        if not text or len(text) > MAX_PROMPT_LENGTH:
            skipped += 1
            continue
        key = prompt_hash(text)
        candidate_keys.append(key)
        # Keyed by hash because one upsert statement cannot touch the same row twice; the later copy wins.
        rows[key] = AEOPrompt(
            team_id=team_id,
            prompt=text,
            prompt_hash=key,
            prompt_source=candidate.source,
            topic=normalize_prompt(candidate.topic)[:PROMPT_TOPIC_MAX_LENGTH],
            rank=candidate.rank,
            evidence=candidate.evidence,
            active=True,
            updated_at=now,
        )
    with team_scope(team_id), transaction.atomic():
        existing = dict(AEOPrompt.objects.filter(prompt_hash__in=rows.keys()).values_list("prompt_hash", "archived_at"))
        # An archived prompt stays archived, so re-importing its text neither revives nor duplicates it.
        archived = {key for key, archived_at in existing.items() if archived_at is not None}
        skipped += sum(1 for key in candidate_keys if key in archived)
        for key in archived:
            del rows[key]
        # `active` is left out of the update, so a re-import keeps prompts someone turned off. So is `prompt`:
        # it copies the current version's text, which only a version change may rewrite.
        # Sorted so concurrent imports lock conflicting rows in the same order and cannot deadlock.
        AEOPrompt.objects.bulk_create(
            [rows[key] for key in sorted(rows)],
            update_conflicts=True,
            unique_fields=["team", "prompt_hash"],
            update_fields=["prompt_source", "topic", "rank", "evidence", "updated_at"],
        )
        new_prompts = AEOPrompt.objects.filter(prompt_hash__in=rows.keys() - existing.keys()).values_list(
            "id", "prompt"
        )
        # ignore_conflicts: a concurrent import of the same new text may have written version 1 first.
        AEOPromptVersion.objects.bulk_create(
            [
                AEOPromptVersion(team_id=team_id, prompt_id=prompt_id, version=1, text=text)
                for prompt_id, text in new_prompts
            ],
            ignore_conflicts=True,
        )
    valid = len(candidates) - skipped
    created = len(rows.keys() - existing.keys())
    if skipped:
        logger.info("aeo_seed_candidates_skipped", team_id=team.id, skipped=skipped)
    return {"created": created, "updated": valid - created, "skipped": skipped}
