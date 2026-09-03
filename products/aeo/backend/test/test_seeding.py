from pathlib import Path

import pytest

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.aeo.backend.engines import MAX_PROMPT_LENGTH
from products.aeo.backend.models import AEOPrompt
from products.aeo.backend.seeding import (
    PromptCandidate,
    import_prompts_csv,
    normalize_prompt,
    prompt_hash,
    upsert_prompts,
)


def test_imports_csv_with_and_without_a_header(tmp_path: Path) -> None:
    with_header = tmp_path / "with_header.csv"
    with_header.write_text("prompt\nWhat is the best web analytics tool?\nBest open source session replay?\n")
    headerless = tmp_path / "headerless.csv"
    headerless.write_text('"What is the best web analytics tool?"\n\nBest open source session replay?\n')

    for path in (with_header, headerless):
        candidates = import_prompts_csv(str(path), source=AEOPrompt.Source.MANUAL)
        assert [c.text for c in candidates] == [
            "What is the best web analytics tool?",
            "Best open source session replay?",
        ]
        assert {c.source for c in candidates} == {AEOPrompt.Source.MANUAL}


def test_prompt_hash_ignores_case_and_whitespace() -> None:
    assert prompt_hash("  Best   Session  Replay?  ") == prompt_hash("best session replay?")
    assert normalize_prompt("  Best   Session  Replay?  ") == "Best Session Replay?"


def _candidate(text: str) -> PromptCandidate:
    return PromptCandidate(text=text, source=AEOPrompt.Source.MANUAL)


@pytest.fixture
def team(db: None) -> Team:
    organization = Organization.objects.create(name="aeo test org")
    return Team.objects.create(organization=organization, name="aeo test team")


def test_reseeding_the_same_prompt_updates_instead_of_duplicating(team: Team) -> None:
    assert upsert_prompts(team, [_candidate("Best session replay?")])["created"] == 1
    result = upsert_prompts(team, [_candidate("  best   SESSION replay?  ")])

    assert result == {"created": 0, "updated": 1, "skipped": 0}
    assert AEOPrompt.objects.for_team(team.id).count() == 1


def test_oversized_and_empty_prompts_are_skipped(team: Team) -> None:
    # A check event only records MAX_PROMPT_LENGTH characters of prompt_text, so a
    # longer prompt would be recorded clipped on every check it runs in.
    result = upsert_prompts(
        team,
        [
            _candidate("What is the best web analytics tool?"),
            _candidate("a" * (MAX_PROMPT_LENGTH + 1)),
            _candidate("   "),
        ],
    )

    assert result == {"created": 1, "updated": 0, "skipped": 2}
    assert [p.prompt for p in AEOPrompt.objects.for_team(team.id)] == ["What is the best web analytics tool?"]
