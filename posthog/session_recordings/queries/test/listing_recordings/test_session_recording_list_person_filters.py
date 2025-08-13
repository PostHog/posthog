from uuid import uuid4

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from parameterized import parameterized

from ee.clickhouse.models.test.test_cohort import get_person_ids_by_cohort_id
from posthog.models import Person
from posthog.session_recordings.queries.test.listing_recordings.test_utils import (
    create_event,
)
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.test.base import (
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from posthog.models.cohort import Cohort
from posthog.session_recordings.queries.test.listing_recordings.test_session_recordings_list_base import (
    BaseTestSessionRecordingsList,
)


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingListPersonFilters(BaseTestSessionRecordingsList):
    @snapshot_clickhouse_queries
    def test_person_id_filter(self):
        three_user_ids = [str(uuid4()) for _ in range(3)]
        session_id_one = f"test_person_id_filter-{str(uuid4())}"
        session_id_two = f"test_person_id_filter-{str(uuid4())}"
        p = Person.objects.create(
            team=self.team,
            distinct_ids=[three_user_ids[0], three_user_ids[1]],
            properties={"email": "bla"},
        )
        produce_replay_summary(
            distinct_id=three_user_ids[0],
            session_id=session_id_one,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=three_user_ids[1],
            session_id=session_id_two,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=three_user_ids[2],
            session_id=str(uuid4()),
            team_id=self.team.id,
        )

        self._assert_query_matches_session_ids({"person_uuid": str(p.uuid)}, [session_id_two, session_id_one])

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["email"])
    def test_filter_with_person_properties_exact(self):
        session_id_one, session_id_two = self._two_sessions_two_persons(
            "test_filter_with_person_properties_exact",
            session_one_person_properties={"email": "bla@gmail.com"},
            session_two_person_properties={"email": "bla2@hotmail.com"},
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    {
                        "key": "email",
                        "value": ["bla@gmail.com"],
                        "operator": "exact",
                        "type": "person",
                    }
                ]
            },
            [session_id_one],
        )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["email"])
    def test_filter_with_person_properties_not_contains(self):
        session_id_one, session_id_two = self._two_sessions_two_persons(
            "test_filter_with_person_properties_not_contains",
            session_one_person_properties={"email": "bla@gmail.com"},
            session_two_person_properties={"email": "bla2@hotmail.com"},
        )

        self._assert_query_matches_session_ids(
            {"properties": [{"key": "email", "value": "gmail.com", "operator": "not_icontains", "type": "person"}]},
            [session_id_two],
        )

    @parameterized.expand(
        [
            ("single_distinct_id", ["test-user-1"], ["session1"]),
            ("multiple_distinct_ids", ["test-user-1", "test-user-2"], ["session1", "session2"]),
            ("non_existent_distinct_id", ["non-existent-user"], []),
            ("empty_distinct_ids", [], ["session1", "session2"]),
        ]
    )
    @snapshot_clickhouse_queries
    def test_filter_by_distinct_ids(self, name: str, distinct_ids: list[str], expected_sessions: list[str]):
        # Create two users with different distinct_ids
        user1 = "test-user-1"
        user2 = "test-user-2"
        Person.objects.create(team=self.team, distinct_ids=[user1])
        Person.objects.create(team=self.team, distinct_ids=[user2])

        # Create sessions for each user
        session1 = f"session1-{uuid4()}"
        session2 = f"session2-{uuid4()}"

        # Create session recordings
        produce_replay_summary(
            distinct_id=user1,
            session_id=session1,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.pk,
        )

        produce_replay_summary(
            distinct_id=user2,
            session_id=session2,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.pk,
        )

        # Map the test's generic session names to actual UUIDs
        session_map = {"session1": session1, "session2": session2}
        expected = [session_map[session] for session in expected_sessions]

        # Test filtering
        self._assert_query_matches_session_ids(query={"distinct_ids": distinct_ids}, expected=expected)

    @also_test_with_materialized_columns(person_properties=["email"], verify_no_jsonextract=False)
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_filter_users_from_excluded_cohort(self):
        """
        Test that sessions from users in a cohort marked as excluded in team test account filters are properly filtered out.
        """
        # Create users
        internal_user = _create_person(
            distinct_ids=["internal_user"],
            team_id=self.team.pk,
            properties={"$is_internal": "yes"},
        )
        actual_user = _create_person(
            distinct_ids=["actual_user"],
            team_id=self.team.pk,
            properties={"$is_internal": "no"},
        )
        # Include internal user in the cohort
        internal_users_cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$is_internal", "value": "yes", "type": "person"}]}],
            name="internal_users_cohort",
        )
        flush_persons_and_events()
        internal_users_cohort.calculate_people_ch(pending_version=0)
        # Check that only internal user is in the cohort
        results = get_person_ids_by_cohort_id(self.team.pk, internal_users_cohort.id)
        assert len(results) == 1
        assert results[0] == str(internal_user.uuid)
        assert results[0] != str(actual_user.uuid)
        # Set up test account filters to exclude the cohort
        self.team.test_account_filters = [
            {
                "key": "id",
                "value": internal_users_cohort.pk,
                "operator": "not_in",
                "type": "cohort",
            }
        ]
        self.team.save()
        # Create replay summaries for both users
        produce_replay_summary(
            distinct_id="internal_user",
            session_id="internal_session",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id="internal_user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "internal_session",
                "$window_id": "1",
            },
        )
        produce_replay_summary(
            distinct_id="internal_user",
            session_id="internal_session",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id="actual_user",
            session_id="actual_session",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id="actual_user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "actual_session",
                "$window_id": "1",
            },
        )
        produce_replay_summary(
            distinct_id="actual_user",
            session_id="actual_session",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )
        # Check that both sessions are returned when filter_test_accounts is False
        self._assert_query_matches_session_ids(
            {
                "filter_test_accounts": False,
            },
            ["internal_session", "actual_session"],
        )
        # Check that only the regular session is returned when filter_test_accounts is True
        self._assert_query_matches_session_ids(
            {
                "filter_test_accounts": True,
            },
            ["actual_session"],
        )

    @also_test_with_materialized_columns(person_properties=["email"], verify_no_jsonextract=False)
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_filter_users_from_excluded_cohort_no_events(self):
        """
        Test that sessions from users in a cohort marked as excluded in team test account filters are properly filtered out,
        even when the session recording don't have any events.
        """
        # Create users
        internal_user = _create_person(
            distinct_ids=["internal_user"],
            team_id=self.team.pk,
            properties={"$is_internal": "yes"},
        )
        actual_user = _create_person(
            distinct_ids=["actual_user"],
            team_id=self.team.pk,
            properties={"$is_internal": "no"},
        )
        # Include internal user in the cohort
        internal_users_cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$is_internal", "value": "yes", "type": "person"}]}],
            name="internal_users_cohort",
        )
        flush_persons_and_events()
        internal_users_cohort.calculate_people_ch(pending_version=0)
        # Check that only internal user is in the cohort
        results = get_person_ids_by_cohort_id(self.team.pk, internal_users_cohort.id)
        assert len(results) == 1
        assert results[0] == str(internal_user.uuid)
        assert results[0] != str(actual_user.uuid)
        # Set up test account filters to exclude the cohort
        self.team.test_account_filters = [
            {
                "key": "id",
                "value": internal_users_cohort.pk,
                "operator": "not_in",
                "type": "cohort",
            }
        ]
        self.team.save()
        # Create replay summaries for both users, but don't create events
        produce_replay_summary(
            distinct_id="internal_user",
            session_id="internal_session",
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id="actual_user",
            session_id="actual_session",
            team_id=self.team.id,
        )
        # Check that both sessions are returned when filter_test_accounts is False
        self._assert_query_matches_session_ids(
            {
                "filter_test_accounts": False,
            },
            ["internal_session", "actual_session"],
        )
        # The assumption is that if the recording has no events - it would still be able to identify what sessions to filter out
        self._assert_query_matches_session_ids(
            {
                "filter_test_accounts": True,
            },
            ["actual_session"],
        )

    @snapshot_clickhouse_queries
    def test_operand_or_person_filters(self):
        user = "test_operand_or_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "test@posthog.com"})

        second_user = "test_operand_or_filter-second_user"
        Person.objects.create(team=self.team, distinct_ids=[second_user], properties={"email": "david@posthog.com"})

        session_id_one = "session_id_one"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        session_id_two = "session_id_two"
        produce_replay_summary(
            distinct_id=second_user,
            session_id=session_id_two,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    {
                        "key": "email",
                        "value": ["test@posthog.com"],
                        "operator": "exact",
                        "type": "person",
                    },
                    {
                        "key": "email",
                        "value": ["david@posthog.com"],
                        "operator": "exact",
                        "type": "person",
                    },
                ],
                "operand": "AND",
            },
            [],
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    {
                        "key": "email",
                        "value": ["test@posthog.com"],
                        "operator": "exact",
                        "type": "person",
                    },
                    {
                        "key": "email",
                        "value": ["david@posthog.com"],
                        "operator": "exact",
                        "type": "person",
                    },
                ],
                "operand": "OR",
            },
            [session_id_one, session_id_two],
        )
