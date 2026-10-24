from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.contrib import admin, messages
from django.contrib.admin import AdminSite
from django.test import RequestFactory

from posthog.admin import register_all_admin
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

from products.aeo.backend.admin import AEOPromptAdmin
from products.aeo.backend.models import AEOPrompt
from products.aeo.backend.seeding import PromptCandidate, upsert_prompts


@pytest.fixture
def team(db: None) -> Team:
    organization = Organization.objects.create(name="aeo admin org")
    return Team.objects.create(organization=organization, name="aeo admin team")


@pytest.fixture
def model_admin() -> AEOPromptAdmin:
    return AEOPromptAdmin(AEOPrompt, AdminSite())


@pytest.fixture
def delay() -> Any:
    with patch("products.aeo.backend.admin.run_aeo_citation_checks_for_team_task") as task:
        yield task.delay


def _request() -> Any:
    request = RequestFactory().post("/")
    request.user = User(pk=1, email="staff@example.com", is_staff=True)
    return request


def _run_action(model_admin: AEOPromptAdmin, team: Team, flag_enabled: bool = True) -> list[tuple[int, str]]:
    with (
        patch("products.aeo.backend.tasks.tasks.feature_enabled_or_false", return_value=flag_enabled),
        patch.object(model_admin, "message_user") as message_user,
    ):
        model_admin.run_citation_checks_now(_request(), AEOPrompt.objects.for_team(team.id).all())
    return [(call.kwargs["level"], call.args[1]) for call in message_user.call_args_list]


@pytest.mark.parametrize(
    "allowlisted,flag_enabled,active,expected_level,expected_text",
    [
        (True, True, True, messages.SUCCESS, "(2 active prompts)"),
        (False, True, True, messages.WARNING, "not in AEO_CITATION_TEAM_IDS"),
        (True, False, True, messages.WARNING, "aeo-citation-tracking flag is off"),
        (True, True, False, messages.WARNING, "no active prompts"),
    ],
    ids=["eligible", "not_allowlisted", "flag_off", "no_active_prompts"],
)
@pytest.mark.usefixtures("cache")
def test_run_now_queues_one_run_per_eligible_team(
    team: Team,
    settings: Any,
    model_admin: AEOPromptAdmin,
    delay: MagicMock,
    allowlisted: bool,
    flag_enabled: bool,
    active: bool,
    expected_level: int,
    expected_text: str,
) -> None:
    settings.AEO_CITATION_TEAM_IDS = [str(team.id)] if allowlisted else []
    upsert_prompts(team, [PromptCandidate(text=f"question {i}?", source="manual") for i in range(2)])
    if not active:
        AEOPrompt.objects.for_team(team.id).update(active=False)

    [(level, text)] = _run_action(model_admin, team, flag_enabled=flag_enabled)
    assert level == expected_level
    assert expected_text in text
    if expected_level == messages.SUCCESS:
        delay.assert_called_once_with(team.id)
    else:
        delay.assert_not_called()


@pytest.mark.usefixtures("cache")
def test_run_now_cooldown_blocks_a_second_run_and_clears_after_a_dispatch_failure(
    team: Team, settings: Any, model_admin: AEOPromptAdmin, delay: MagicMock
) -> None:
    settings.AEO_CITATION_TEAM_IDS = [str(team.id)]
    upsert_prompts(team, [PromptCandidate(text="question?", source="manual")])

    delay.side_effect = RuntimeError("broker down")
    [(level, _)] = _run_action(model_admin, team)
    assert level == messages.ERROR

    delay.side_effect = None
    [(level, _)] = _run_action(model_admin, team)
    assert level == messages.SUCCESS

    [(level, text)] = _run_action(model_admin, team)
    assert level == messages.WARNING
    assert "already queued" in text
    assert delay.call_count == 2


def test_prompt_admin_is_registered_by_admin_autodiscovery() -> None:
    register_all_admin()

    assert admin.site.is_registered(AEOPrompt)


def test_changelist_queryset_lists_prompts_from_every_team(team: Team, model_admin: AEOPromptAdmin) -> None:
    other_team = Team.objects.create(organization=team.organization, name="other aeo team")
    upsert_prompts(team, [PromptCandidate(text="first?", source="manual")])
    upsert_prompts(other_team, [PromptCandidate(text="second?", source="manual")])

    listed = model_admin.get_queryset(RequestFactory().get("/"))

    assert set(listed.values_list("team_id", flat=True)) == {team.id, other_team.id}
