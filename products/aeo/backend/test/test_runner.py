import datetime as dt

import pytest

from django.utils import timezone

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.aeo.backend.config import resolve_config
from products.aeo.backend.engines import CitationCheck
from products.aeo.backend.facade.api import update_config
from products.aeo.backend.facade.contracts import AEOConfig, Competitor
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
        return CitationCheck(
            engine=self.name,
            model=self.model,
            cited_urls=["https://posthog.com/docs"],
            answer_text="PostHog answers this one.",
        )


@pytest.mark.parametrize("via_child_environment", [False, True])
def test_run_records_checks_and_rotates_without_a_team_scope(team: Team, settings, via_child_environment: bool) -> None:
    settings.AEO_TARGET_DOMAINS = ["posthog.com"]
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
    assert checks.filter(brand_mentioned=True).count() == 4
    assert {c.prompt_topic for c in checks} == {"t0", "t1"}
    assert len({c.prompt_id for c in checks}) == 4


class _FailingEngine:
    name = "failing-engine"
    model = "stub"

    def run(self, prompt: str, *, trace_id: str, custom_properties: dict[str, str]) -> CitationCheck:
        return CitationCheck(engine=self.name, model=self.model, error="HTTPError: status=500")


def test_run_keeps_detection_null_on_a_failed_check(team: Team, settings) -> None:
    settings.AEO_TARGET_DOMAINS = ["posthog.com"]
    upsert_prompts(team, [PromptCandidate(text="q?", source="imported")])

    run_citation_checks(team, engines=[_FailingEngine()], limit=1)

    check = AEOCitationCheck.objects.for_team(team.id).get()
    assert check.check_failed is True
    assert (check.brand_mentioned, check.competitors_mentioned, check.competitors_cited) == (None, None, None)


@pytest.mark.parametrize("stored", [False, True])
def test_resolve_config_falls_back_to_the_global_setting(team: Team, settings, stored: bool) -> None:
    settings.AEO_TARGET_DOMAINS = ["example.co.uk"]
    expected = AEOConfig(target_domains=("example.co.uk",), brand_names=("example",), competitors=())
    if stored:
        expected = update_config(
            team.id,
            target_domains=["Brand.example.net", "brand.example.net"],
            brand_names=["Brand Co"],
            competitors=[Competitor(name="Rival", domains=("rival.example.net",))],
        )
        assert expected.target_domains == ("brand.example.net",)

    assert resolve_config(team.id) == expected
