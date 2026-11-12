from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.utils import timezone

from posthog.models.team import Team

from products.ai_observability.backend.eval_suggestions import eligibility
from products.ai_observability.backend.eval_suggestions.config import SuggestionSettings
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


class TestSteadyTraffic(ClickhouseTestMixin, BaseTest):
    def test_a_team_needs_generations_on_enough_recent_days(self) -> None:
        now = timezone.now()
        quiet = Team.objects.create(organization=self.organization, name="quiet")
        # Steady: 4 days in the last 28, two of them in the last week. Quiet: 3 days, all in the last week.
        for team, days_ago in ((self.team, (1, 3, 10, 20)), (quiet, (1, 2, 3))):
            for days in days_ago:
                _create_event(
                    team=team,
                    event="$ai_generation",
                    distinct_id="user-1",
                    timestamp=now - timedelta(days=days),
                    properties={"$ai_trace_id": f"trace-{days}"},
                )

        assert eligibility.steady_traffic_team_ids([self.team.pk, quiet.pk], now) == {self.team.pk}
