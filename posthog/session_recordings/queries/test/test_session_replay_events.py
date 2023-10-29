from posthog.models import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.test.base import ClickhouseTestMixin, APIBaseTest
from dateutil.relativedelta import relativedelta
from django.utils.timezone import now


class SessionReplayEventsQueries(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        produce_replay_summary(
            session_id="1",
            team_id=self.team.pk,
            first_timestamp=self.base_time.isoformat(),
            last_timestamp=self.base_time.isoformat(),
            distinct_id="u1",
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=50 * 1000 * 0.5,
        )
        produce_replay_summary(
            session_id="2",
            team_id=self.team.pk,
            first_timestamp=self.base_time.isoformat(),
            last_timestamp=self.base_time.isoformat(),
            distinct_id="u1",
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=50 * 1000 * 0.5,
        )

    def test_get_metadata(self) -> None:
        metadata = SessionReplayEvents().get_metadata(session_id="1", team=self.team)
        assert metadata == {
            "active_seconds": 25.0,
            "click_count": 2,
            "console_error_count": 0,
            "console_log_count": 0,
            "console_warn_count": 0,
            "distinct_id": "u1",
            "duration": 0,
            "end_time": self.base_time,
            "first_url": "https://example.io/home",
            "keypress_count": 2,
            "mouse_activity_count": 2,
            "start_time": self.base_time,
        }

    def test_get_nonexistent_metadata(self) -> None:
        metadata = SessionReplayEvents().get_metadata(session_id="not a session", team=self.team)
        assert metadata is None

    def test_get_metadata_does_not_leak_between_teams(self) -> None:
        another_team = Team.objects.create(organization=self.organization, name="Another Team")
        metadata = SessionReplayEvents().get_metadata(session_id="1", team=another_team)
        assert metadata is None

    def test_get_metadata_filters_by_date(self) -> None:
        metadata = SessionReplayEvents().get_metadata(
            session_id="1",
            team=self.team,
            recording_start_time=self.base_time + relativedelta(days=2),
        )
        assert metadata is None
