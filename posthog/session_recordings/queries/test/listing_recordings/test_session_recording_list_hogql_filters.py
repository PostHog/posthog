from uuid import uuid4

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from posthog.models import Person
from posthog.session_recordings.queries.test.listing_recordings.base_test_session_recordings_list import (
    BaseTestSessionRecordingsList,
)
from posthog.session_recordings.queries.test.listing_recordings.test_utils import create_event
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.base import also_test_with_materialized_columns, snapshot_clickhouse_queries


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingListHogQLFilters(BaseTestSessionRecordingsList):
    @also_test_with_materialized_columns(event_properties=["$current_url", "$browser"], person_properties=["email"])
    @snapshot_clickhouse_queries
    def test_event_filter_with_hogql_properties(self):
        user = "test_event_filter_with_hogql_properties-user"

        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id = f"test_event_filter_with_hogql_properties-1-{str(uuid4())}"
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
            properties={
                "$browser": "Chrome",
                "$session_id": session_id,
                "$window_id": str(uuid4()),
            },
        )

        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        self._assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [
                            {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
                        ],
                    }
                ]
            },
            [session_id],
        )

        self._assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [{"key": "properties.$browser == 'Firefox'", "type": "hogql"}],
                    }
                ]
            },
            [],
        )

    @snapshot_clickhouse_queries
    def test_event_filter_with_hogql_person_properties(self):
        user = "test_event_filter_with_hogql_properties-user"

        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id = f"test_event_filter_with_hogql_properties-1-{str(uuid4())}"
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
            properties={
                "$browser": "Chrome",
                "$session_id": session_id,
                "$window_id": str(uuid4()),
            },
        )

        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        self._assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [
                            {
                                "key": "person.properties.email == 'bla'",
                                "type": "hogql",
                            },
                        ],
                    }
                ]
            },
            [session_id],
        )

        self._assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [
                            {
                                "key": "person.properties.email == 'something else'",
                                "type": "hogql",
                            },
                        ],
                    }
                ]
            },
            [],
        )

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_event_filter_with_hogql_event_properties_test_accounts_excluded(self):
        self.team.test_account_filters = [
            {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
        ]
        self.team.save()

        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(
            team=self.team,
            distinct_ids=["user2"],
            properties={"email": "not-the-other-one"},
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={"$session_id": "1", "$window_id": "1", "$browser": "Chrome"},
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id="user2",
            timestamp=self.an_hour_ago,
            properties={"$session_id": "2", "$window_id": "1", "$browser": "Firefox"},
        )

        self._assert_query_matches_session_ids(
            {
                # there are 2 pageviews
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": False,
            },
            ["1", "2"],
        )

        self.team.test_account_filters = [
            {"key": "person.properties.email == 'bla'", "type": "hogql"},
        ]
        self.team.save()

        self._assert_query_matches_session_ids(
            {
                # only 1 pageview that matches the hogql test_accounts filter
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": True,
            },
            ["1"],
        )

        self.team.test_account_filters = [
            {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
            {"key": "person.properties.email == 'bla'", "type": "hogql"},
        ]
        self.team.save()

        # one user sessions matches the person + event test_account filter
        self._assert_query_matches_session_ids(
            {
                "filter_test_accounts": True,
            },
            ["1"],
        )

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_top_level_hogql_event_property_test_account_filter(self):
        """
        This is a regression test. A user with an $ip test account filter
        reported the filtering wasn't working.

        The filter wasn't triggering the "should join events" check, and so we didn't apply the filter at all
        """
        self.team.test_account_filters = [
            {"key": "properties.is_internal_user == 'true'", "type": "hogql"},
        ]
        self.team.save()

        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(
            team=self.team,
            distinct_ids=["user2"],
            properties={"email": "not-the-other-one"},
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id="user2",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        self._assert_query_matches_session_ids(
            {
                # there are 2 pageviews
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": False,
            },
            ["1", "2"],
        )

        self._assert_query_matches_session_ids(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
            ["2"],
        )

    @also_test_with_materialized_columns(person_properties=["email"], verify_no_jsonextract=False)
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_top_level_hogql_person_property_test_account_filter(self):
        """
        This is a regression test. A user with an $ip test account filter
        reported the filtering wasn't working.

        The filter wasn't triggering the "should join events" check, and so we didn't apply the filter at all
        """
        self.team.test_account_filters = [
            {"key": "person.properties.email == 'bla'", "type": "hogql"},
        ]
        self.team.save()

        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(
            team=self.team,
            distinct_ids=["user2"],
            properties={"email": "not-the-other-one"},
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id="user2",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        self._assert_query_matches_session_ids(
            {
                # there are 2 pageviews
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": False,
            },
            ["1", "2"],
        )

        self._assert_query_matches_session_ids(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
            ["1"],
        )
