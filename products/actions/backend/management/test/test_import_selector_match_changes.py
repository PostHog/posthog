import json

import pytest

from django.core.management import call_command

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.actions.backend.models import Action, ActionSelectorMatchChange

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def team():
    return create_team(organization=create_organization("test org"))


def _report(path, teams):
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-11T00:00:00+00:00",
                "teams": {str(team_id): {"autocapture_events": 100, "rows": rows} for team_id, rows in teams.items()},
            }
        )
    )
    return str(path)


def _flagged_row(team_id, action_id, selector):
    return {
        "team_id": team_id,
        "action_id": action_id,
        "step_index": 0,
        "selector": selector,
        "bucket": "no_faithful_fix",
        "counts": {"old_original": 900, "new_original": 120},
    }


def test_re_import_clears_a_team_the_report_no_longer_flags(team, tmp_path):
    action = Action.objects.create(team=team, name="checkout", steps_json=[{"selector": ".btn"}])
    call_command(
        "import_selector_match_changes",
        report=_report(tmp_path / "first.json", {team.id: [_flagged_row(team.id, action.id, ".btn")]}),
        live_run=True,
    )
    assert ActionSelectorMatchChange.objects.for_team(team.id).count() == 1

    call_command(
        "import_selector_match_changes",
        report=_report(tmp_path / "second.json", {team.id: []}),
        live_run=True,
    )
    assert ActionSelectorMatchChange.objects.for_team(team.id).count() == 0


def test_import_leaves_a_team_the_report_does_not_cover(team, tmp_path):
    other = create_team(organization=create_organization("other org"))
    action = Action.objects.create(team=other, name="checkout", steps_json=[{"selector": ".btn"}])
    call_command(
        "import_selector_match_changes",
        report=_report(tmp_path / "first.json", {other.id: [_flagged_row(other.id, action.id, ".btn")]}),
        live_run=True,
    )

    call_command(
        "import_selector_match_changes",
        report=_report(tmp_path / "second.json", {team.id: []}),
        live_run=True,
    )

    assert ActionSelectorMatchChange.objects.for_team(other.id).count() == 1
