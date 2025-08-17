from unittest.mock import ANY

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from posthog.models import Person
from posthog.session_recordings.queries.test.listing_recordings.test_base_session_recordings_list import (
    BaseTestSessionRecordingsList,
)
from posthog.session_recordings.queries.test.listing_recordings.test_utils import create_event
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.base import also_test_with_materialized_columns, snapshot_clickhouse_queries


class TestSessionRecordingListTestAccounts(BaseTestSessionRecordingsList):
    def test_event_filter_with_test_accounts_excluded(self):
        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            },
            {
                "key": "is_internal_user",
                "value": ["false"],
                "operator": "exact",
                # in production some test account filters don't include type
                # we default to event in that case
                # "type": "event",
            },
            {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
        ]
        self.team.save()

        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

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
                "is_internal_user": "true",
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        self.assert_query_matches_session_ids(
            {
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
            [],
        )

        self.assert_query_matches_session_ids(
            {
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
            ["1"],
        )

    def test_top_level_event_property_test_account_filter(self):
        """
        This is a regression test. A user with an $ip test account filter
        reported the filtering wasn't working.

        The filter wasn't triggering the "should join events check", and so we didn't apply the filter at all
        """
        self.team.test_account_filters = [
            {
                "key": "is_internal_user",
                "value": ["false"],
                "operator": "exact",
                "type": "event",
            },
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

        self.assert_query_matches_session_ids(
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

        self.assert_query_matches_session_ids(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
            ["1"],
        )

    # TRICKY: we had to disable use of materialized columns for part of the query generation
    # due to RAM usage issues on the EU cluster
    @also_test_with_materialized_columns(event_properties=["is_internal_user"], verify_no_jsonextract=True)
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_top_level_event_property_test_account_filter_allowing_denormalized_props(self):
        """
        This is a duplicate of the test test_top_level_event_property_test_account_filter
        but with denormalized props allowed
        """

        with self.settings(ALLOW_DENORMALIZED_PROPS_IN_LISTING=True):
            self.team.test_account_filters = [
                {
                    "key": "is_internal_user",
                    "value": ["false"],
                    "operator": "exact",
                    "type": "event",
                },
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

            self.assert_query_matches_session_ids(
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

            self.assert_query_matches_session_ids(
                {
                    # only 1 pageview that matches the test_accounts filter
                    "filter_test_accounts": True,
                },
                ["1"],
            )

    def test_top_level_person_property_test_account_filter(self):
        """
        This is a regression test. A user with an $ip test account filter
        reported the filtering wasn't working.

        The filter wasn't triggering the "should join events" check, and so we didn't apply the filter at all
        """
        self.team.test_account_filters = [{"key": "email", "value": ["bla"], "operator": "exact", "type": "person"}]
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
                "event": "something that won't match",
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
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

        # there are 2 pageviews
        self.assert_query_matches_session_ids(
            {
                # pageview that matches the hogql test_accounts filter
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

        self.assert_query_matches_session_ids(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
            ["1"],
        )

    def test_top_level_event_host_property_test_account_filter(self):
        """
        This is a regression test. See: https://posthoghelp.zendesk.com/agent/tickets/18059
        """
        self.team.test_account_filters = [
            {"key": "$host", "type": "event", "value": "^(localhost|127\\.0\\.0\\.1)($|:)", "operator": "not_regex"},
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
        # the session needs to have multiple matching or not matching events
        for _ in range(10):
            create_event(
                team=self.team,
                distinct_id="user",
                timestamp=self.an_hour_ago,
                properties={
                    "$session_id": "1",
                    "$window_id": "1",
                    "$host": "localhost",
                },
            )

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
            click_count=10,
        )

        for _ in range(10):
            create_event(
                team=self.team,
                distinct_id="user2",
                timestamp=self.an_hour_ago,
                properties={
                    "$session_id": "2",
                    "$window_id": "1",
                    "$host": "example.com",
                },
            )
        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            click_count=10,
        )

        # there are 2 pageviews
        self.assert_query_matches_session_ids(
            {
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

        (session_recordings, _, _) = self.filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            }
        )

        assert session_recordings == [
            {
                "active_seconds": 0.0,
                "activity_score": 0.28,
                "click_count": 10,  # in the bug this value was 10 X number of events in the session
                "console_error_count": 0,
                "console_log_count": 0,
                "console_warn_count": 0,
                "distinct_id": "user2",
                "duration": 3600,
                "end_time": ANY,
                "first_url": "https://not-provided-by-test.com",
                "inactive_seconds": 3600.0,
                "keypress_count": 0,
                "mouse_activity_count": 0,
                "session_id": "2",
                "start_time": ANY,
                "team_id": self.team.id,
                "ongoing": 1,
            }
        ]
