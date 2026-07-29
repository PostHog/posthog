from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from posthog.session_recordings.queries.session_replay_url_values import get_visited_page_values
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary


class TestVisitedPageValues(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_time = (now() - relativedelta(days=1)).replace(microsecond=0)

    def _produce(self, session_id: str, all_urls: list[str], days_ago: int = 1) -> None:
        timestamp = (now() - relativedelta(days=days_ago)).replace(microsecond=0)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=session_id,
            distinct_id="u1",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            first_url=all_urls[0] if all_urls else None,
            all_urls=all_urls,
        )

    def test_returns_urls_recorded_without_any_pageview_events(self):
        # The whole point of the fix: no $pageview events exist, only replay data
        self._produce("s1", ["https://example.com/pricing", "https://example.com/billing"])
        self._produce("s2", ["https://example.com/pricing"])

        assert sorted(get_visited_page_values(team=self.team)) == [
            "https://example.com/billing",
            "https://example.com/pricing",
        ]

    def test_filters_by_search_value(self):
        self._produce("s1", ["https://example.com/pricing", "https://example.com/billing"])

        assert get_visited_page_values(team=self.team, search_value="BILL") == ["https://example.com/billing"]

    def test_excludes_other_teams_and_recordings_outside_the_window(self):
        other_team = self.create_team_with_organization(self.organization)
        produce_replay_summary(
            team_id=other_team.pk,
            session_id="other",
            distinct_id="u2",
            first_timestamp=self.base_time,
            last_timestamp=self.base_time,
            all_urls=["https://other-team.com/secret"],
        )
        self._produce("old", ["https://example.com/ancient"], days_ago=45)
        self._produce("recent", ["https://example.com/pricing"])

        assert get_visited_page_values(team=self.team) == ["https://example.com/pricing"]
