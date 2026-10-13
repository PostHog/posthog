from datetime import datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.team.team_event_volume import TeamEventVolume
from posthog.tasks.team_event_volume import _month_starts, update_team_event_volumes


class TestMonthStarts(SimpleTestCase):
    @parameterized.expand(
        [
            ("full_year", datetime(2025, 9, 30), datetime(2026, 9, 30), 13, "202509", "202609"),
            ("leap_february", datetime(2024, 1, 31), datetime(2024, 3, 1), 3, "202401", "202403"),
            ("single_month", datetime(2026, 9, 2), datetime(2026, 9, 20), 1, "202609", "202609"),
            ("ends_on_month_boundary", datetime(2026, 8, 15), datetime(2026, 9, 1), 2, "202608", "202609"),
        ]
    )
    def test_covers_every_month_the_window_touches(
        self, _name: str, start: datetime, end: datetime, count: int, first: str, last: str
    ) -> None:
        ids = [month.strftime("%Y%m") for month in _month_starts(start, end)]

        assert len(ids) == count
        assert ids == sorted(set(ids))
        assert (ids[0], ids[-1]) == (first, last)


class TestUpdateTeamEventVolumes(ClickhouseTestMixin, BaseTest):
    def test_counts_only_the_last_year_per_team_and_zeroes_teams_that_went_quiet(self) -> None:
        quiet = Team.objects.create(organization=self.organization, name="quiet")
        TeamEventVolume.objects.unscoped().create(
            team=quiet, events_last_year=5, computed_at=timezone.now() - timedelta(days=1)
        )
        _create_event(team=self.team, event="e", distinct_id="a", timestamp=timezone.now() - timedelta(days=1))
        _create_event(team=self.team, event="e", distinct_id="a", timestamp=timezone.now() - timedelta(days=200))
        _create_event(team=self.team, event="e", distinct_id="a", timestamp=timezone.now() - timedelta(days=400))
        _create_event(team=self.team, event="e", distinct_id="a", timestamp=timezone.now() + timedelta(days=30))
        flush_persons_and_events()

        with patch("posthog.tasks.team_event_volume.set_team_event_volume_last_success") as set_last_success:
            update_team_event_volumes()

        volume = TeamEventVolume.objects.for_team(self.team.id).get()
        assert volume.events_last_year == 2
        assert TeamEventVolume.objects.for_team(quiet.id).get().events_last_year == 0
        set_last_success.assert_called_once_with(volume.computed_at)

    def test_does_not_write_last_success_when_budget_is_disabled(self) -> None:
        with (
            patch("posthog.tasks.team_event_volume.budget_enabled", return_value=False),
            patch("posthog.tasks.team_event_volume.set_team_event_volume_last_success") as set_last_success,
        ):
            update_team_event_volumes()

        set_last_success.assert_not_called()
