from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event

from django.utils import timezone

from posthog.models.team import Team

from products.ai_observability.backend.logic.eval_suggestions.eligibility_queries import (
    GenerationDaysRow,
    load_generation_days,
)


class TestGenerationDays(ClickhouseTestMixin, BaseTest):
    def test_counts_each_teams_generation_days_in_the_last_28_and_7_days(self) -> None:
        now = timezone.now()
        quiet = Team.objects.create(organization=self.organization, name="quiet")
        for team, days_ago in ((self.team, (1, 3, 10, 20)), (quiet, (1, 2, 3))):
            for days in days_ago:
                _create_event(
                    team=team,
                    event="$ai_generation",
                    distinct_id="user-1",
                    timestamp=now - timedelta(days=days),
                    properties={"$ai_trace_id": f"trace-{days}"},
                )

        rows = load_generation_days([self.team.pk, quiet.pk], now)

        assert sorted(rows, key=lambda row: row.team_id) == [
            GenerationDaysRow(team_id=self.team.pk, days_28=4, days_7=2),
            GenerationDaysRow(team_id=quiet.pk, days_28=3, days_7=3),
        ]
