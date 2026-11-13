from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.team import Team

from products.ai_observability.backend.logic.eval_suggestions import eligibility
from products.ai_observability.backend.logic.eval_suggestions.config import SuggestionSettings
from products.ai_observability.backend.logic.eval_suggestions.eligibility_queries import GenerationDaysRow
from products.ai_observability.backend.models.eval_suggestions import EvalSuggestionTeamState


class TestEligibility(BaseTest):
    def test_traffic_is_checked_only_until_the_cap_is_filled(self) -> None:
        teams = [self.team, *(Team.objects.create(organization=self.organization, name=f"t{i}") for i in range(3))]
        for team in teams:
            EvalSuggestionTeamState.objects.for_team(team.pk).create(team=team, last_visited_at=timezone.now())

        with (
            patch.object(eligibility, "is_enabled_for_organization", return_value=True),
            patch.object(eligibility, "TRAFFIC_BATCH", 1),
            patch.object(eligibility, "steady_traffic_team_ids", side_effect=lambda ids, now: set(ids)) as steady,
        ):
            eligible = eligibility.eligible_team_ids(SuggestionSettings(max_teams_per_run=2))

        assert len(eligible) == 2
        assert steady.call_count == 2

    def test_a_child_environment_records_every_visit_on_its_root_team(self) -> None:
        child = Team.objects.create(organization=self.organization, project=self.team.project, parent_team=self.team)

        eligibility.record_visit(child)
        eligibility.record_visit(child)

        assert EvalSuggestionTeamState.objects.for_team(self.team.pk).count() == 1


@parameterized.expand(
    [
        ("four_days_two_this_week", 4, 2, True),
        ("three_days_all_this_week", 3, 3, False),
        ("four_days_one_this_week", 4, 1, False),
    ]
)
def test_a_team_needs_generations_on_enough_recent_days(_name: str, days_28: int, days_7: int, expected: bool) -> None:
    rows = [GenerationDaysRow(team_id=1, days_28=days_28, days_7=days_7)]
    assert (eligibility.steady_traffic(rows) == {1}) is expected
