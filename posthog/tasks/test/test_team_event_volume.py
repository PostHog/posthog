from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from posthog.models import Team
from posthog.models.team.team_event_volume import TeamEventVolume
from posthog.tasks.team_event_volume import update_team_event_volumes


class TestUpdateTeamEventVolumes(ClickhouseTestMixin, BaseTest):
    def test_counts_the_last_year_per_team_and_zeroes_teams_that_went_quiet(self) -> None:
        quiet = Team.objects.create(organization=self.organization, name="quiet")
        TeamEventVolume.objects.unscoped().create(
            team=quiet, events_last_year=5, computed_at=timezone.now() - timedelta(days=1)
        )
        _create_event(team=self.team, event="e", distinct_id="a")
        _create_event(team=self.team, event="e", distinct_id="a")
        _create_event(team=self.team, event="e", distinct_id="a", timestamp=timezone.now() - timedelta(days=400))
        flush_persons_and_events()

        update_team_event_volumes()

        assert TeamEventVolume.objects.for_team(self.team.id).get().events_last_year == 2
        assert TeamEventVolume.objects.for_team(quiet.id).get().events_last_year == 0
