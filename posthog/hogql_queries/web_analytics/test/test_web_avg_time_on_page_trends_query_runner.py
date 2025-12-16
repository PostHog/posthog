from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    IntervalType,
    PropertyOperator,
    WebAvgTimeOnPageTrendsQuery,
    WebAvgTimeOnPageTrendsQueryResponse,
)

from posthog.hogql_queries.web_analytics.web_avg_time_on_page_trends_query_runner import (
    WebAvgTimeOnPageTrendsQueryRunner,
)
from posthog.models.utils import uuid7


class TestWebAvgTimeOnPageTrendsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-10"

    def _create_pageview_event(
        self,
        distinct_id: str,
        timestamp: str,
        session_id: str,
        prev_pageview_duration: float | None = None,
        prev_pageview_pathname: str | None = None,
    ):
        properties: dict[str, Any] = {
            "$session_id": session_id,
        }
        if prev_pageview_duration is not None:
            properties["$prev_pageview_duration"] = prev_pageview_duration
        if prev_pageview_pathname is not None:
            properties["$prev_pageview_pathname"] = prev_pageview_pathname

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties=properties,
        )

    def _run_query(
        self,
        date_from: str = "-7d",
        date_to: str | None = None,
        interval: IntervalType = IntervalType.DAY,
        properties: list | None = None,
    ) -> WebAvgTimeOnPageTrendsQueryResponse:
        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebAvgTimeOnPageTrendsQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                interval=interval,
                properties=properties or [],
            )
            runner = WebAvgTimeOnPageTrendsQueryRunner(
                team=self.team,
                query=query,
                modifiers=HogQLQueryModifiers(),
            )
            response = runner.calculate()
            WebAvgTimeOnPageTrendsQueryResponse.model_validate(response)
            return response

    def test_multiple_views_in_single_session_averaged_correctly(self):
        _create_person(team_id=self.team.pk, distinct_ids=["user1"])

        self._create_pageview_event("user1", "2025-01-10 10:00:00", "session1")
        self._create_pageview_event("user1", "2025-01-10 10:01:00", "session1", prev_pageview_duration=100)
        self._create_pageview_event("user1", "2025-01-10 10:02:00", "session1", prev_pageview_duration=200)
        self._create_pageview_event("user1", "2025-01-10 10:03:00", "session1", prev_pageview_duration=300)

        response = self._run_query(date_from="2025-01-10", date_to="2025-01-10")

        assert len(response.results) == 1

        assert response.results[0].avgTimeOnPage == 200

    def test_multiple_sessions_in_single_day_averaged_correctly(self):
        """Average time is calculated correctly when there are multiple sessions in a single day."""
        _create_person(team_id=self.team.pk, distinct_ids=["user1"])
        _create_person(team_id=self.team.pk, distinct_ids=["user2"])

        self._create_pageview_event("user1", "2025-01-10 10:00:00", "session1")
        self._create_pageview_event("user1", "2025-01-10 10:01:00", "session1", prev_pageview_duration=100)
        self._create_pageview_event("user1", "2025-01-10 10:02:00", "session1", prev_pageview_duration=200)

        self._create_pageview_event("user2", "2025-01-10 14:00:00", "session2")
        self._create_pageview_event("user2", "2025-01-10 14:01:00", "session2", prev_pageview_duration=400)
        self._create_pageview_event("user2", "2025-01-10 14:02:00", "session2", prev_pageview_duration=600)

        response = self._run_query(date_from="2025-01-10", date_to="2025-01-10")

        assert len(response.results) == 1

        assert response.results[0].avgTimeOnPage == 325.0

    def test_null_prev_pageview_duration_excluded(self):
        _create_person(team_id=self.team.pk, distinct_ids=["user1"])

        self._create_pageview_event("user1", "2025-01-10 10:00:00", "session1")
        self._create_pageview_event("user1", "2025-01-10 10:01:00", "session1", prev_pageview_duration=500)
        self._create_pageview_event("user1", "2025-01-10 10:02:00", "session1", prev_pageview_duration=None)
        self._create_pageview_event("user1", "2025-01-10 10:03:00", "session1", prev_pageview_duration=300)

        response = self._run_query(date_from="2025-01-10", date_to="2025-01-10")

        assert len(response.results) == 1

        assert response.results[0].avgTimeOnPage == 400.0

    def test_pathname_filter_uses_prev_pageview_pathname(self):
        _create_person(team_id=self.team.pk, distinct_ids=["user1"])

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2025-01-10 10:00:00",
            properties={
                "$session_id": "session1",
                "$pathname": "/pricing",
                "$prev_pageview_duration": 100,
                "$prev_pageview_pathname": "/",
            },
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2025-01-10 10:01:00",
            properties={
                "$session_id": "session1",
                "$pathname": "/",
                "$prev_pageview_duration": 999,
                "$prev_pageview_pathname": "/pricing",
            },
        )

        response = self._run_query(
            date_from="2025-01-10",
            date_to="2025-01-10",
            properties=[
                EventPropertyFilter(
                    key="$pathname",
                    operator=PropertyOperator.EXACT,
                    value="/",
                )
            ],
        )

        assert len(response.results) == 1

        assert response.results[0].avgTimeOnPage == 100.0

    def test_single_event_in_session(self):
        """Average is correctly calculated when there is only a single event with duration in a session."""
        _create_person(team_id=self.team.pk, distinct_ids=["user1"])

        self._create_pageview_event("user1", "2025-01-10 10:00:00", "session1")
        self._create_pageview_event("user1", "2025-01-10 10:05:00", "session1", prev_pageview_duration=750)

        response = self._run_query(date_from="2025-01-10", date_to="2025-01-10")

        assert len(response.results) == 1

        assert response.results[0].avgTimeOnPage == 750.0

    def test_days_with_no_events_not_returned(self):
        _create_person(team_id=self.team.pk, distinct_ids=["user1"])

        self._create_pageview_event("user1", "2025-01-10 10:00:00", "session1")
        self._create_pageview_event("user1", "2025-01-10 10:01:00", "session1", prev_pageview_duration=100)

        response = self._run_query(date_from="2025-01-10", date_to="2025-01-12")
        buckets = [r.bucket for r in response.results]

        assert len(response.results) == 1
        assert "2025-01-10" in buckets[0]

    def test_outer_avg_aggregates_session_averages_correctly(self):
        _create_person(team_id=self.team.pk, distinct_ids=["user1"])
        _create_person(team_id=self.team.pk, distinct_ids=["user2"])
        _create_person(team_id=self.team.pk, distinct_ids=["user3"])

        self._create_pageview_event("user1", "2025-01-10 09:00:00", "session1")
        self._create_pageview_event("user1", "2025-01-10 09:01:00", "session1", prev_pageview_duration=100)

        self._create_pageview_event("user2", "2025-01-10 10:00:00", "session2")
        self._create_pageview_event("user2", "2025-01-10 10:01:00", "session2", prev_pageview_duration=200)

        self._create_pageview_event("user3", "2025-01-10 11:00:00", "session3")
        self._create_pageview_event("user3", "2025-01-10 11:01:00", "session3", prev_pageview_duration=300)

        response = self._run_query(date_from="2025-01-10", date_to="2025-01-10")

        assert len(response.results) == 1

        assert response.results[0].avgTimeOnPage == 200.0

    def test_hourly_interval_buckets_correctly(self):
        """Hourly interval groups events into hour-based buckets."""
        _create_person(team_id=self.team.pk, distinct_ids=["user1"])

        session1 = str(uuid7())
        session2 = str(uuid7())

        self._create_pageview_event("user1", "2025-01-10 10:00:00", session1)
        self._create_pageview_event("user1", "2025-01-10 10:30:00", session1, prev_pageview_duration=100)

        self._create_pageview_event("user1", "2025-01-10 11:00:00", session2)
        self._create_pageview_event("user1", "2025-01-10 11:30:00", session2, prev_pageview_duration=200)

        response = self._run_query(
            date_from="2025-01-10",
            date_to="2025-01-11",
            interval=IntervalType.HOUR,
        )

        assert len(response.results) == 2

        buckets = sorted([r.bucket for r in response.results])

        assert buckets[0] == "2025-01-10 10:00:00+00:00"
        assert buckets[1] == "2025-01-10 11:00:00+00:00"

    def test_weekly_interval_buckets_correctly(self):
        """Weekly interval groups events into week-based buckets."""
        _create_person(team_id=self.team.pk, distinct_ids=["user1"])

        session1 = str(uuid7())
        session2 = str(uuid7())

        self._create_pageview_event("user1", "2025-01-06 10:00:00", session1)
        self._create_pageview_event("user1", "2025-01-06 10:01:00", session1, prev_pageview_duration=100)

        self._create_pageview_event("user1", "2025-01-13 10:00:00", session2)
        self._create_pageview_event("user1", "2025-01-13 10:01:00", session2, prev_pageview_duration=200)

        response = self._run_query(
            date_from="2025-01-01",
            date_to="2025-01-20",
            interval=IntervalType.WEEK,
        )

        assert len(response.results) == 2
