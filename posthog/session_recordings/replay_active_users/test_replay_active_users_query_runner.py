from datetime import datetime, timedelta
from freezegun import freeze_time

from posthog.schema import ReplayActiveUsersQuery
from posthog.session_recordings.replay_active_users.replay_active_users_query_runner import (
    ReplayActiveUsersQueryRunner,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    _create_event,
    snapshot_clickhouse_queries,
    flush_persons_and_events,
)


@freeze_time("2024-01-15T12:00:00Z")
class TestReplayActiveUsersQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

    def test_basic_query_returns_active_users(self):
        # Create some test persons
        _create_person(
            distinct_ids=["user1"],
            team=self.team,
            properties={"email": "user1@example.com", "name": "User One"},
        )
        _create_person(
            distinct_ids=["user2"],
            team=self.team,
            properties={"email": "user2@example.com", "name": "User Two"},
        )
        _create_person(
            distinct_ids=["user3"],
            team=self.team,
            properties={"email": "user3@example.com", "name": "User Three"},
        )

        # Create replay events for the users within the last 7 days
        base_time = datetime.now()

        # User 1 - 3 sessions
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user1",
            session_id="session1_1",
            first_timestamp=base_time - timedelta(days=1),
            last_timestamp=base_time - timedelta(days=1, seconds=-60),
        )
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user1",
            session_id="session1_2",
            first_timestamp=base_time - timedelta(days=2),
            last_timestamp=base_time - timedelta(days=2, seconds=-60),
        )
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user1",
            session_id="session1_3",
            first_timestamp=base_time - timedelta(days=3),
            last_timestamp=base_time - timedelta(days=3, seconds=-60),
        )

        # User 2 - 2 sessions
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user2",
            session_id="session2_1",
            first_timestamp=base_time - timedelta(days=1),
            last_timestamp=base_time - timedelta(days=1, seconds=-60),
        )
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user2",
            session_id="session2_2",
            first_timestamp=base_time - timedelta(days=2),
            last_timestamp=base_time - timedelta(days=2, seconds=-60),
        )

        # User 3 - 1 session
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user3",
            session_id="session3_1",
            first_timestamp=base_time - timedelta(days=1),
            last_timestamp=base_time - timedelta(days=1, seconds=-60),
        )

        # Create a session that's too short (should be filtered out)
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user1",
            session_id="session1_short",
            first_timestamp=base_time - timedelta(days=1),
            last_timestamp=base_time - timedelta(days=1, seconds=-3),
        )

        # Create a session that's too old (should be filtered out)
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user1",
            session_id="session1_old",
            first_timestamp=base_time - timedelta(days=8),
            last_timestamp=base_time - timedelta(days=8, seconds=-60),
        )

        # Create additional events for the sessions with proper event types
        _create_event(
            distinct_id="user1",
            event="$pageview",
            properties={"$session_id": "session1_1"},
            team=self.team,
            timestamp=base_time - timedelta(days=1),
        )
        _create_event(
            distinct_id="user1",
            event="$pageview",
            properties={"$session_id": "session1_2"},
            team=self.team,
            timestamp=base_time - timedelta(days=2),
        )
        _create_event(
            distinct_id="user1",
            event="$pageview",
            properties={"$session_id": "session1_3"},
            team=self.team,
            timestamp=base_time - timedelta(days=3),
        )
        _create_event(
            distinct_id="user2",
            event="$pageview",
            properties={"$session_id": "session2_1"},
            team=self.team,
            timestamp=base_time - timedelta(days=1),
        )
        _create_event(
            distinct_id="user2",
            event="$pageview",
            properties={"$session_id": "session2_2"},
            team=self.team,
            timestamp=base_time - timedelta(days=2),
        )
        _create_event(
            distinct_id="user3",
            event="$pageview",
            properties={"$session_id": "session3_1"},
            team=self.team,
            timestamp=base_time - timedelta(days=1),
        )

        flush_persons_and_events()

        # Run the query
        query = ReplayActiveUsersQuery()
        runner = ReplayActiveUsersQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        # Verify results
        assert len(response.results) > 0

        # Results should be sorted by count descending
        counts = [r.count for r in response.results]
        assert counts == sorted(counts, reverse=True)

        # User 1 should have the most sessions (3)
        top_user = response.results[0]
        assert top_user.count == 3
        assert top_user.person.properties["email"] == "user1@example.com"

    def test_query_filters_short_sessions(self):
        # Create a person
        _create_person(
            distinct_ids=["user_short"],
            team=self.team,
            properties={"email": "short@example.com"},
        )

        base_time = datetime.now()

        # Create only short sessions (< 5 seconds)
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user_short",
            session_id="short1",
            first_timestamp=base_time - timedelta(days=1),
            last_timestamp=base_time - timedelta(days=1, seconds=-2),
        )
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user_short",
            session_id="short2",
            first_timestamp=base_time - timedelta(days=2),
            last_timestamp=base_time - timedelta(days=2, seconds=-3),
        )
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user_short",
            session_id="short3",
            first_timestamp=base_time - timedelta(days=3),
            last_timestamp=base_time - timedelta(days=3, seconds=-4),
        )
        flush_persons_and_events()

        # Run the query
        query = ReplayActiveUsersQuery()
        runner = ReplayActiveUsersQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        # User should not appear in results since all sessions are too short
        user_emails = [r.person.properties.get("email") for r in response.results]
        assert "short@example.com" not in user_emails

    def test_query_filters_old_sessions(self):
        # Create a person
        _create_person(
            distinct_ids=["user_old"],
            team=self.team,
            properties={"email": "old@example.com"},
        )

        base_time = datetime.now()

        # Create only old sessions (> 7 days ago)
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user_old",
            session_id="old1",
            first_timestamp=base_time - timedelta(days=8),
            last_timestamp=base_time - timedelta(days=8, seconds=-60),
        )
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user_old",
            session_id="old2",
            first_timestamp=base_time - timedelta(days=10),
            last_timestamp=base_time - timedelta(days=10, seconds=-60),
        )
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="user_old",
            session_id="old3",
            first_timestamp=base_time - timedelta(days=15),
            last_timestamp=base_time - timedelta(days=15, seconds=-60),
        )
        flush_persons_and_events()

        # Run the query
        query = ReplayActiveUsersQuery()
        runner = ReplayActiveUsersQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        # User should not appear in results since all sessions are too old
        user_emails = [r.person.properties.get("email") for r in response.results]
        assert "old@example.com" not in user_emails

    def test_query_returns_top_10_users(self):
        # Create 15 persons with varying session counts
        base_time = datetime.now()

        for i in range(15):
            _create_person(
                distinct_ids=[f"user{i}"],
                team=self.team,
                properties={"email": f"user{i}@example.com", "index": i},
            )

            # Create different number of sessions for each user
            # User 0 gets 15 sessions, user 1 gets 14, etc.
            for j in range(15 - i):
                produce_replay_summary(
                    team_id=self.team.pk,
                    distinct_id=f"user{i}",
                    session_id=f"session_{i}_{j}",
                    first_timestamp=base_time - timedelta(days=1, hours=j),
                    last_timestamp=base_time - timedelta(days=1, hours=j, seconds=-60),
                )
                # Create events for each session
                _create_event(
                    distinct_id=f"user{i}",
                    event="$pageview",
                    properties={"$session_id": f"session_{i}_{j}"},
                    team=self.team,
                    timestamp=base_time - timedelta(days=1, hours=j),
                )

        flush_persons_and_events()

        # Run the query
        query = ReplayActiveUsersQuery()
        runner = ReplayActiveUsersQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        # Should return exactly 10 users
        assert len(response.results) == 10

        # Should be the top 10 users by session count
        for i, result in enumerate(response.results):
            expected_count = 15 - i
            assert result.count == expected_count
            assert result.person.properties["index"] == i

    @snapshot_clickhouse_queries
    def test_query_performance(self):
        # Create some test data
        _create_person(
            distinct_ids=["perf_user"],
            team=self.team,
            properties={"email": "perf@example.com"},
        )

        base_time = datetime.now()
        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="perf_user",
            session_id="perf_session",
            first_timestamp=base_time - timedelta(days=1),
            last_timestamp=base_time - timedelta(days=1, seconds=-60),
        )
        flush_persons_and_events()

        # Run the query and capture queries
        query = ReplayActiveUsersQuery()
        runner = ReplayActiveUsersQueryRunner(query=query, team=self.team)
        response = runner.calculate()

        assert response.results is not None
