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

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.aeo.backend.engines import MAX_PROMPT_LENGTH
from products.aeo.backend.models import AEOPrompt

logger = structlog.get_logger(__name__)


@frozen
class PromptCandidate:
    text: str
    source: str
    rank: float = 0
    evidence: dict[str, Any] = field(default_factory=dict)


def normalize_prompt(text: str) -> str:
    return " ".join(text.strip().split())


def prompt_hash(text: str) -> str:
    return hashlib.sha256(normalize_prompt(text).lower().encode("utf-8")).hexdigest()


def import_prompts_csv(path: str, *, source: str = AEOPrompt.Source.IMPORTED) -> list[PromptCandidate]:
    """Import prompts from a CSV — either a file with a `prompt` header column,
    or a headerless file with one prompt per line."""
    with open(path, newline="") as f:
        first_row = next(csv.reader(f), None)
        f.seek(0)
        has_header = first_row is not None and any(cell.strip().lower() == "prompt" for cell in first_row)
        texts: list[str] = []
        if has_header:
            for row in csv.DictReader(f):
                text = next((value for key, value in row.items() if key and key.strip().lower() == "prompt"), None)
                if text and text.strip():
                    texts.append(text.strip())
        else:
            for line in f:
                text = line.strip().strip('"')
                if text:
                    texts.append(text)
    return [PromptCandidate(text=text, source=source, evidence={"file": path}) for text in texts]


def upsert_prompts(team: Team, candidates: list[PromptCandidate]) -> dict[str, int]:
    """Write the candidates to the prompt set, skipping empty and oversized ones.

    MAX_PROMPT_LENGTH is a payload-size guard, not a security control: it keeps a
    single prompt from bloating every check event it appears on, and it matches
    what a check event records for prompt_text.
    """
    created = updated = skipped = 0
    for candidate in candidates:
        text = normalize_prompt(candidate.text)
        if not text or len(text) > MAX_PROMPT_LENGTH:
            skipped += 1
            continue
        # for_team scopes the fail-closed manager; team is still passed
        # explicitly because queryset filters don't propagate into row creation.
        _, was_created = AEOPrompt.objects.for_team(team.id).update_or_create(
            team=team,
            prompt_hash=prompt_hash(text),
            defaults={
                "prompt": text,
                "prompt_source": candidate.source,
                "rank": candidate.rank,
                "evidence": candidate.evidence,
                "active": True,
            },
        )
        created += was_created
        updated += not was_created
    if skipped:
        logger.info("aeo_seed_candidates_skipped", team_id=team.id, skipped=skipped)
    return {"created": created, "updated": updated, "skipped": skipped}
