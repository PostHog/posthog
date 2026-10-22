import datetime as dt

import pytest

from django.utils import timezone

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.aeo.backend.engines import CitationCheck
from products.aeo.backend.models import AEOCitationCheck, AEOPrompt
from products.aeo.backend.runner import run_citation_checks, select_prompts
from products.aeo.backend.seeding import PromptCandidate, upsert_prompts


@pytest.fixture
def team(db: None) -> Team:
    organization = Organization.objects.create(name="aeo test org")
    return Team.objects.create(organization=organization, name="aeo test team")


def test_select_prompts_alternates_topics_and_rotates_to_least_recently_checked(team: Team) -> None:
    upsert_prompts(
        team,
        [
            *(PromptCandidate(text=f"replay question {i}?", source="imported", topic="Replay") for i in range(5)),
            PromptCandidate(text="flags question?", source="imported", topic="Flags"),
            PromptCandidate(text="untagged question?", source="imported"),
        ],
    )
    prompts = AEOPrompt.objects.for_team(team.id)
    prompts.filter(prompt="replay question 0?").update(last_checked_at=timezone.now())
    prompts.filter(prompt="flags question?").update(last_checked_at=timezone.now() - dt.timedelta(days=1))

    selected = [p.prompt for p in select_prompts(team, limit=4)]

    assert len(selected) == 4
    assert {p.split(" question")[0] for p in selected} == {"replay", "flags", "untagged"}
    assert "replay question 0?" not in selected


def test_select_prompts_skips_inactive_prompts(team: Team) -> None:
    upsert_prompts(team, [PromptCandidate(text=f"q{i}?", source="imported") for i in range(3)])
    AEOPrompt.objects.for_team(team.id).filter(prompt="q1?").update(active=False)

    assert sorted(p.prompt for p in select_prompts(team, limit=10)) == ["q0?", "q2?"]


class _StubEngine:
    name = "stub-engine"
    model = "stub"

    def run(self, prompt: str, *, trace_id: str, custom_properties: dict[str, str]) -> CitationCheck:
        return CitationCheck(engine=self.name, model=self.model, cited_urls=["https://posthog.com/docs"])


@pytest.mark.parametrize("via_child_environment", [False, True])
@pytest.mark.parametrize("concurrency", [1, 4])
def test_run_records_checks_and_rotates_without_a_team_scope(
    team: Team, settings, via_child_environment: bool, concurrency: int
) -> None:
    settings.AEO_TARGET_DOMAINS = ["posthog.com"]
    settings.AEO_RUN_CONCURRENCY = concurrency
    runner_team = (
        Team.objects.create(organization=team.organization, name="child env", parent_team=team)
        if via_child_environment
        else team
    )
    upsert_prompts(
        runner_team, [PromptCandidate(text=f"q{i}?", source="imported", topic=f"t{i % 2}") for i in range(4)]
    )

    first, _ = run_citation_checks(runner_team, engines=[_StubEngine()], limit=2)
    second, _ = run_citation_checks(runner_team, engines=[_StubEngine()], limit=2)

    assert (first.rows_written, second.rows_written) == (2, 2)
    checks = AEOCitationCheck.objects.for_team(team.id)
    assert checks.filter(cited=True).count() == 4
    assert {c.prompt_topic for c in checks} == {"t0", "t1"}
    assert len({c.prompt_id for c in checks}) == 4


class _CrashingEngine(_StubEngine):
    def run(self, prompt: str, *, trace_id: str, custom_properties: dict[str, str]) -> CitationCheck:
        if prompt == "q1?":
            raise RuntimeError("unexpected engine bug")
        return super().run(prompt, trace_id=trace_id, custom_properties=custom_properties)


def test_one_prompt_crashing_does_not_end_the_run(team: Team, settings) -> None:
    settings.AEO_RUN_CONCURRENCY = 2
    settings.AEO_MAX_PROMPTS_PER_RUN = 3
    upsert_prompts(team, [PromptCandidate(text=f"q{i}?", source="imported", topic="t") for i in range(3)])

    summary, _ = run_citation_checks(team, engines=[_CrashingEngine()])

    assert (summary.prompts, summary.rows_written, summary.engine_failures) == (3, 2, 1)
    assert sorted(AEOCitationCheck.objects.for_team(team.id).values_list("prompt_text", flat=True)) == ["q0?", "q2?"]
