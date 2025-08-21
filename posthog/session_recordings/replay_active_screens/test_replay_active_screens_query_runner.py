from datetime import datetime, timedelta
from freezegun import freeze_time
from uuid import uuid4

from posthog.schema import ReplayActiveScreensQuery
from posthog.session_recordings.replay_active_screens.replay_active_screens_query_runner import (
    ReplayActiveScreensQueryRunner,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    snapshot_clickhouse_queries,
    flush_persons_and_events,
)


@freeze_time("2024-01-15T12:00:00Z")
class TestReplayActiveScreensQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

    def test_basic_query_returns_active_screens(self):
        # Create some test persons
        _create_person(
            distinct_ids=["user1"],
            team=self.team,
        )
        _create_person(
            distinct_ids=["user2"],
            team=self.team,
        )

        # Create replay events with different URLs within the last 7 days
        base_time = datetime.now()

        # Session 1 with URL https://app.posthog.com/insights
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user1",
            session_id=str(uuid4()),
            first_timestamp=base_time - timedelta(days=1),
            last_timestamp=base_time - timedelta(days=1, seconds=-60),
            all_urls=["https://app.posthog.com/insights", "https://app.posthog.com/insights/123"],
        )

        # Session 2 with URL https://app.posthog.com/dashboard
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user1",
            session_id=str(uuid4()),
            first_timestamp=base_time - timedelta(days=2),
            last_timestamp=base_time - timedelta(days=2, seconds=-60),
            all_urls=["https://app.posthog.com/dashboard"],
        )

        # Session 3 with same URL as session 1 (different user)
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user2",
            session_id=str(uuid4()),
            first_timestamp=base_time - timedelta(days=1),
            last_timestamp=base_time - timedelta(days=1, seconds=-60),
            all_urls=["https://app.posthog.com/insights"],
        )

        # Create a session that's too short (should be filtered out)
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user1",
            session_id=str(uuid4()),
            first_timestamp=base_time - timedelta(days=1),
            last_timestamp=base_time - timedelta(days=1, seconds=-3),
            all_urls=["https://app.posthog.com/features"],
        )

        # Create a session that's too old (should be filtered out)
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user1",
            session_id=str(uuid4()),
            first_timestamp=base_time - timedelta(days=8),
            last_timestamp=base_time - timedelta(days=8, seconds=-60),
            all_urls=["https://app.posthog.com/old"],
        )

        flush_persons_and_events()

        # Run the query
        query = ReplayActiveScreensQuery()
        runner = ReplayActiveScreensQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        # Verify results
        assert len(response.results) > 0

        # Results should be sorted by count descending
        counts = [r.count for r in response.results]
        assert counts == sorted(counts, reverse=True)

        # Find insights screen in results
        insights_result = next((r for r in response.results if "insights" in r.screen), None)
        assert insights_result is not None
        assert insights_result.count == 2  # 2 sessions with insights URLs

        # Find dashboard screen in results
        dashboard_result = next((r for r in response.results if "dashboard" in r.screen), None)
        assert dashboard_result is not None
        assert dashboard_result.count == 1  # 1 session with dashboard URL

    def test_query_filters_short_sessions(self):
        # Create a person
        _create_person(
            distinct_ids=["user_short"],
            team=self.team,
        )

        base_time = datetime.now()

        # Create only short sessions (< 5 seconds)
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user_short",
            session_id="short1",
            first_timestamp=base_time - timedelta(days=1),
            last_timestamp=base_time - timedelta(days=1, seconds=-2),
            all_urls=["https://app.posthog.com/features"],
        )

        flush_persons_and_events()

        # Run the query
        query = ReplayActiveScreensQuery()
        runner = ReplayActiveScreensQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        # Features screen should not appear in results since the session is too short
        features_result = next((r for r in response.results if "features" in r.screen), None)
        assert features_result is None

    def test_query_filters_old_sessions(self):
        # Create a person
        _create_person(
            distinct_ids=["user_old"],
            team=self.team,
        )

        base_time = datetime.now()

        # Create only old sessions (> 7 days ago)
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user_old",
            session_id="old1",
            first_timestamp=base_time - timedelta(days=8),
            last_timestamp=base_time - timedelta(days=8, seconds=-60),
            all_urls=["https://app.posthog.com/old-screen"],
        )

        flush_persons_and_events()

        # Run the query
        query = ReplayActiveScreensQuery()
        runner = ReplayActiveScreensQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        # Old screen should not appear in results since the session is too old
        old_screen_result = next((r for r in response.results if "old-screen" in r.screen), None)
        assert old_screen_result is None

    def test_query_returns_top_10_screens(self):
        # Create a person
        _create_person(
            distinct_ids=["user"],
            team=self.team,
        )

        base_time = datetime.now()

        # Create 15 sessions with different URLs
        for i in range(15):
            produce_replay_summary(
                team_id=self.team.pk,
                distinct_id="user",
                session_id=f"session_{i}",
                first_timestamp=base_time - timedelta(days=1, hours=i),
                last_timestamp=base_time - timedelta(days=1, hours=i, seconds=-60),
                all_urls=[f"https://app.posthog.com/screen{i}"],
            )

        flush_persons_and_events()

        # Run the query
        query = ReplayActiveScreensQuery()
        runner = ReplayActiveScreensQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        # Should return exactly 10 screens (due to LIMIT 10)
        assert len(response.results) <= 10

    @snapshot_clickhouse_queries
    def test_query_performance(self):
        # Create some test data
        _create_person(
            distinct_ids=["perf_user"],
            team=self.team,
        )

        base_time = datetime.now()
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="perf_user",
            session_id=str(uuid4()),
            first_timestamp=base_time - timedelta(days=1),
            last_timestamp=base_time - timedelta(days=1, seconds=-60),
            all_urls=["https://app.posthog.com/performance"],
        )
        flush_persons_and_events()

        # Run the query and capture queries
        query = ReplayActiveScreensQuery()
        runner = ReplayActiveScreensQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        assert response.results is not None
