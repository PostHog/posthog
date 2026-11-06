from posthog.test.base import BaseTest
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
            EvalSuggestionTeamState.objects.create(team=team, last_visited_at=timezone.now())

        with (
            patch.object(eligibility, "is_enabled_for_organization", return_value=True),
            patch.object(eligibility, "TRAFFIC_BATCH", 1),
            patch.object(eligibility, "steady_traffic_team_ids", side_effect=lambda ids, now: set(ids)) as steady,
        ):
            eligible = eligibility.eligible_team_ids(SuggestionSettings(max_teams_per_run=2))

        assert len(eligible) == 2
        assert steady.call_count == 2
