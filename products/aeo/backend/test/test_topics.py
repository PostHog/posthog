import threading
from typing import Any

import pytest
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test.utils import CaptureQueriesContext

from posthog.models.organization import Organization
from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.aeo.backend import topics
from products.aeo.backend.engines import CitationCheck
from products.aeo.backend.facade.api import update_prompt
from products.aeo.backend.facade.contracts import CheckMode, PromptTopicConflictError, PromptUpdate
from products.aeo.backend.models import AEOCitationCheck, AEOPrompt
from products.aeo.backend.runner import run_citation_checks
from products.aeo.backend.seeding import PromptCandidate, upsert_prompts
from products.aeo.backend.test.factories import create_own_brand


def _team() -> Team:
    organization = Organization.objects.create(name="aeo topics org")
    team = Team.objects.create(organization=organization, name="aeo topics team")
    create_own_brand(team, "example.com")
    return team


@pytest.mark.django_db(transaction=True)
def test_concurrent_renames_onto_one_name_give_the_second_a_conflict() -> None:
    team = _team()
    upsert_prompts(
        team,
        [
            PromptCandidate(text="a?", source="imported", topic="Pricing"),
            PromptCandidate(text="b?", source="imported", topic="Plans"),
        ],
    )
    first_relabeling = threading.Event()
    release_first = threading.Event()
    second_done = threading.Event()
    outcomes: dict[str, Any] = {}
    relabel = topics._relabel

    def hold_first_relabel(team_id: int, old: str, new: str) -> Any:
        result = relabel(team_id, old, new)
        if old == "Pricing":
            first_relabeling.set()
            release_first.wait(timeout=30)
        return result

    def rename(name: str, old: str, done: threading.Event | None = None) -> None:
        try:
            with team_scope(team.pk):
                outcomes[name] = topics.rename_topic(team.id, old, "Cost")
        except PromptTopicConflictError as error:
            outcomes[name] = error
        finally:
            close_old_connections()
            if done is not None:
                done.set()

    with patch.object(topics, "_relabel", hold_first_relabel):
        first = threading.Thread(target=rename, args=("first", "Pricing"))
        first.start()
        assert first_relabeling.wait(timeout=30)
        second = threading.Thread(target=rename, args=("second", "Plans", second_done))
        second.start()
        # The second rename waits on the first one's lock instead of reading "Cost" as free.
        assert not second_done.wait(timeout=1)
        release_first.set()
        first.join(timeout=30)
        second.join(timeout=30)

    assert isinstance(outcomes["second"], PromptTopicConflictError)
    assert dict(AEOPrompt.objects.for_team(team.id).values_list("prompt", "topic")) == {"a?": "Cost", "b?": "Plans"}


class _RenamingEngine:
    """Renames the topic while it answers, the way an edit lands while a run is in flight."""

    name = "stub-engine"
    model = "stub"
    mode = CheckMode.WEB_SEARCH

    def __init__(self, team_id: int) -> None:
        self.team_id = team_id

    def run(self, prompt: str, *, trace_id: str, custom_properties: dict[str, str]) -> CitationCheck:
        with team_scope(self.team_id):
            topics.rename_topic(self.team_id, "Pricing", "Cost")
        return CitationCheck(engine=self.name, model=self.model, cited_urls=["https://docs.example.com/guide"])


@pytest.mark.django_db(transaction=True)
def test_a_check_recorded_after_a_rename_takes_the_new_topic(settings) -> None:
    settings.AEO_RUN_CONCURRENCY = 1
    team = _team()
    upsert_prompts(team, [PromptCandidate(text="a?", source="imported", topic="Pricing")])

    run_citation_checks(team, engines=[_RenamingEngine(team.id)], limit=1)

    # The run read the prompt before the rename, so its snapshot still says Pricing.
    assert list(AEOCitationCheck.objects.for_team(team.id).values_list("prompt_topic", flat=True)) == ["Cost"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "edit",
    [
        lambda team_id, ids: topics.set_topic(team_id, ids, "Cost"),
        lambda team_id, ids: topics.rename_topic(team_id, "Pricing", "Cost"),
    ],
    ids=["set_topic", "rename"],
)
def test_topic_edits_lock_prompts_in_the_order_imports_lock_them(edit: Any) -> None:
    team = _team()
    upsert_prompts(team, [PromptCandidate(text=f"q{i}?", source="imported", topic="Pricing") for i in range(3)])
    ids = list(AEOPrompt.objects.for_team(team.id).values_list("id", flat=True))

    with team_scope(team.pk), CaptureQueriesContext(connection) as queries:
        edit(team.id, ids)

    # `upsert_prompts` locks by prompt_hash. Two transactions that lock the same rows in different orders deadlock.
    prompt_locks = [
        query["sql"]
        for query in queries.captured_queries
        if "FOR UPDATE" in query["sql"] and '"posthog_aeo_prompt"' in query["sql"]
    ]
    assert prompt_locks
    assert all('ORDER BY "posthog_aeo_prompt"."prompt_hash"' in sql for sql in prompt_locks)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "write",
    [
        lambda team, prompt_id: update_prompt(team.id, str(prompt_id), PromptUpdate(topic="Cost"), user_id=None),
        # Paused, so the import takes no prompt-limit lock of its own.
        lambda team, _: upsert_prompts(
            team, [PromptCandidate(text="new?", source="imported", topic="Cost", active=False)]
        ),
    ],
    ids=["single_prompt_edit", "paused_import"],
)
def test_a_prompt_write_that_sets_a_topic_waits_for_a_topic_edit(write: Any) -> None:
    team = _team()
    upsert_prompts(
        team,
        [
            PromptCandidate(text="a?", source="imported", topic="Plans"),
            PromptCandidate(text="b?", source="imported", topic="Other"),
        ],
    )
    other = AEOPrompt.objects.for_team(team.id).get(prompt="b?").id
    renaming = threading.Event()
    release_rename = threading.Event()
    write_done = threading.Event()
    relabel = topics._relabel

    def hold_relabel(team_id: int, old: str, new: str) -> Any:
        result = relabel(team_id, old, new)
        renaming.set()
        release_rename.wait(timeout=30)
        return result

    def rename() -> None:
        try:
            with team_scope(team.pk):
                topics.rename_topic(team.id, "Plans", "Cost")
        finally:
            close_old_connections()

    def run_write() -> None:
        try:
            with team_scope(team.pk):
                write(team, other)
        finally:
            close_old_connections()
            write_done.set()

    with patch.object(topics, "_relabel", hold_relabel):
        renaming_thread = threading.Thread(target=rename)
        renaming_thread.start()
        assert renaming.wait(timeout=30)
        writing_thread = threading.Thread(target=run_write)
        writing_thread.start()
        # The write waits for the rename's lock, so a rename never checks a name a concurrent write is adding.
        assert not write_done.wait(timeout=1)
        release_rename.set()
        renaming_thread.join(timeout=30)
        writing_thread.join(timeout=30)

    assert write_done.is_set()
