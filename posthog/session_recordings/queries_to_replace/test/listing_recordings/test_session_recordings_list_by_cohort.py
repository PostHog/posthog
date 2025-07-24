from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.models import Cohort, Person
from posthog.session_recordings.queries_to_replace.test.listing_recordings.test_utils import (
    create_event,
    assert_query_matches_session_ids,
)
from posthog.session_recordings.queries_to_replace.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    also_test_with_materialized_columns,
    snapshot_clickhouse_queries,
)


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingsListByCohort(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

    # wrap the util so we don't have to pass team every time
    def _assert_query_matches_session_ids(
        self, query: dict | None, expected: list[str], sort_results_when_asserting: bool = True
    ) -> None:
        assert_query_matches_session_ids(
            team=self.team, query=query, expected=expected, sort_results_when_asserting=sort_results_when_asserting
        )

    @property
    def an_hour_ago(self):
        return (now() - relativedelta(hours=1)).replace(microsecond=0, second=0)

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["$some_prop"])
    def test_filter_with_cohort_properties(self) -> None:
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            with freeze_time("2021-08-21T20:00:00.000Z"):
                user_one = "test_filter_with_cohort_properties-user"
                user_two = "test_filter_with_cohort_properties-user2"
                session_id_one = "session_not_in_cohort"
                session_id_two = "session_in_cohort"

                Person.objects.create(team=self.team, distinct_ids=[user_one], properties={"email": "bla"})
                Person.objects.create(
                    team=self.team,
                    distinct_ids=[user_two],
                    properties={"email": "bla2", "$some_prop": "some_val"},
                )
                cohort = Cohort.objects.create(
                    team=self.team,
                    name="cohort1",
                    groups=[
                        {
                            "properties": [
                                {
                                    "key": "$some_prop",
                                    "value": "some_val",
                                    "type": "person",
                                }
                            ]
                        }
                    ],
                )
                cohort.calculate_people_ch(pending_version=0)

                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.an_hour_ago,
                    team_id=self.team.id,
                )
                # self.create_event(user_one, self.base_time, team=self.team)
                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                    team_id=self.team.id,
                )
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.an_hour_ago,
                    team_id=self.team.id,
                )
                # self.create_event(user_two, self.base_time, team=self.team)
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                    team_id=self.team.id,
                )

                self._assert_query_matches_session_ids(
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": cohort.pk,
                                "operator": "in",
                                "type": "cohort",
                            }
                        ]
                    },
                    [session_id_two],
                )

                self._assert_query_matches_session_ids(
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": cohort.pk,
                                "operator": "not_in",
                                "type": "cohort",
                            }
                        ]
                    },
                    [session_id_one],
                )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["$some_prop"])
    def test_filter_with_static_and_dynamic_cohort_properties(self):
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            with freeze_time("2021-08-21T20:00:00.000Z"):
                user_one = "test_filter_with_cohort_properties-user-in-static-cohort"
                user_two = "test_filter_with_cohort_properties-user2-in-dynamic-cohort"
                user_three = "test_filter_with_cohort_properties-user3-in-both-cohort"
                user_four = "test_filter_with_cohort_properties-user4-not-in-any-cohort"

                session_id_one = (
                    f"in-static-cohort-test_filter_with_static_and_dynamic_cohort_properties-1-{str(uuid4())}"
                )
                session_id_two = (
                    f"in-dynamic-cohort-test_filter_with_static_and_dynamic_cohort_properties-2-{str(uuid4())}"
                )
                session_id_three = (
                    f"in-both-cohort-test_filter_with_static_and_dynamic_cohort_properties-3-{str(uuid4())}"
                )
                session_id_four = (
                    f"not-in-any-cohort-test_filter_with_static_and_dynamic_cohort_properties-4-{str(uuid4())}"
                )

                Person.objects.create(team=self.team, distinct_ids=[user_one], properties={"email": "in@static.cohort"})
                Person.objects.create(
                    team=self.team,
                    distinct_ids=[user_two],
                    properties={"email": "in@dynamic.cohort", "$some_prop": "some_val"},
                )
                Person.objects.create(
                    team=self.team,
                    distinct_ids=[user_three],
                    properties={"email": "in@both.cohorts", "$some_prop": "some_val"},
                )

                dynamic_cohort = Cohort.objects.create(
                    team=self.team,
                    name="cohort1",
                    groups=[
                        {
                            "properties": [
                                {
                                    "key": "$some_prop",
                                    "value": "some_val",
                                    "type": "person",
                                }
                            ]
                        }
                    ],
                )

                static_cohort = Cohort.objects.create(team=self.team, name="a static cohort", groups=[], is_static=True)
                static_cohort.insert_users_by_list([user_one, user_three])

                dynamic_cohort.calculate_people_ch(pending_version=0)
                static_cohort.calculate_people_ch(pending_version=0)

                replay_summaries = [
                    (user_one, session_id_one),
                    (user_two, session_id_two),
                    (user_three, session_id_three),
                ]
                for distinct_id, session_id in replay_summaries:
                    produce_replay_summary(
                        distinct_id=distinct_id,
                        session_id=session_id,
                        first_timestamp=self.an_hour_ago,
                        team_id=self.team.id,
                    )
                    produce_replay_summary(
                        distinct_id=distinct_id,
                        session_id=session_id,
                        first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                        team_id=self.team.id,
                    )

                self._assert_query_matches_session_ids(
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": static_cohort.pk,
                                "operator": "in",
                                "type": "cohort",
                            },
                        ]
                    },
                    [session_id_one, session_id_three],
                )

                self._assert_query_matches_session_ids(
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": static_cohort.pk,
                                "operator": "not_in",
                                "type": "cohort",
                            },
                        ]
                    },
                    [session_id_two],
                )

                self._assert_query_matches_session_ids(
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": dynamic_cohort.pk,
                                "operator": "in",
                                "type": "cohort",
                            },
                        ]
                    },
                    [session_id_two, session_id_three],
                )

                self._assert_query_matches_session_ids(
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": dynamic_cohort.pk,
                                "operator": "not_in",
                                "type": "cohort",
                            },
                        ]
                    },
                    [session_id_one],
                )

                self._assert_query_matches_session_ids(
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": dynamic_cohort.pk,
                                "operator": "not_in",
                                "type": "cohort",
                            },
                            {
                                "key": "id",
                                "value": static_cohort.pk,
                                "operator": "not_in",
                                "type": "cohort",
                            },
                        ]
                    },
                    [],
                )

                # and now with users not in any cohort

                Person.objects.create(
                    team=self.team, distinct_ids=[user_four], properties={"email": "not.in.any@cohorts.com"}
                )
                produce_replay_summary(
                    distinct_id=user_four,
                    session_id=session_id_four,
                    team_id=self.team.id,
                )

                self._assert_query_matches_session_ids(
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": dynamic_cohort.pk,
                                "operator": "not_in",
                                "type": "cohort",
                            },
                            {
                                "key": "id",
                                "value": static_cohort.pk,
                                "operator": "not_in",
                                "type": "cohort",
                            },
                        ]
                    },
                    [session_id_four],
                )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["$some_prop"])
    def test_filter_with_events_and_cohorts(self):
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            with freeze_time("2021-08-21T20:00:00.000Z"):
                user_one = "test_filter_with_events_and_cohorts-user"
                user_two = "test_filter_with_events_and_cohorts-user2"
                session_id_one = f"test_filter_with_events_and_cohorts-1-{str(uuid4())}"
                session_id_two = f"test_filter_with_events_and_cohorts-2-{str(uuid4())}"

                Person.objects.create(team=self.team, distinct_ids=[user_one], properties={"email": "bla"})
                Person.objects.create(
                    team=self.team,
                    distinct_ids=[user_two],
                    properties={"email": "bla2", "$some_prop": "some_val"},
                )
                cohort = Cohort.objects.create(
                    team=self.team,
                    name="cohort1",
                    groups=[
                        {
                            "properties": [
                                {
                                    "key": "$some_prop",
                                    "value": "some_val",
                                    "type": "person",
                                }
                            ]
                        }
                    ],
                )
                cohort.calculate_people_ch(pending_version=0)

                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.an_hour_ago,
                    team_id=self.team.id,
                )
                create_event(
                    user_one,
                    self.an_hour_ago,
                    team=self.team,
                    event_name="custom_event",
                    properties={"$session_id": session_id_one},
                )
                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                    team_id=self.team.id,
                )
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.an_hour_ago,
                    team_id=self.team.id,
                )
                create_event(
                    user_two,
                    self.an_hour_ago,
                    team=self.team,
                    event_name="custom_event",
                    properties={"$session_id": session_id_two},
                )
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                    team_id=self.team.id,
                )

                self._assert_query_matches_session_ids(
                    {
                        # has to be in the cohort and pageview has to be in the events
                        # test data has one user in the cohort but no pageviews
                        "properties": [
                            {
                                "key": "id",
                                "value": cohort.pk,
                                "operator": "in",
                                "type": "cohort",
                            }
                        ],
                        "events": [
                            {
                                "id": "$pageview",
                                "type": "events",
                                "order": 0,
                                "name": "$pageview",
                            }
                        ],
                    },
                    [],
                )

                self._assert_query_matches_session_ids(
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": cohort.pk,
                                "operator": "in",
                                "type": "cohort",
                            }
                        ],
                        "events": [
                            {
                                "id": "custom_event",
                                "type": "events",
                                "order": 0,
                                "name": "custom_event",
                            }
                        ],
                    },
                    [session_id_two],
                )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["$some_prop"])
    def test_internal_account_filter_with_cohort_properties(self) -> None:
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            with freeze_time("2021-08-21T20:00:00.000Z"):
                user_one = "test_filter_with_cohort_properties-user"
                user_two = "test_filter_with_cohort_properties-user2"
                session_id_one = "session_not_in_cohort"
                session_id_two = "session_in_cohort"

                Person.objects.create(team=self.team, distinct_ids=[user_one], properties={"email": "bla"})
                Person.objects.create(
                    team=self.team,
                    distinct_ids=[user_two],
                    properties={"email": "bla2", "$some_prop": "some_val"},
                )
                cohort = Cohort.objects.create(
                    team=self.team,
                    name="cohort1",
                    groups=[
                        {
                            "properties": [
                                {
                                    "key": "$some_prop",
                                    "value": "some_val",
                                    "type": "person",
                                }
                            ]
                        }
                    ],
                )
                cohort.calculate_people_ch(pending_version=0)

                self.team.test_account_filters = [
                    {
                        "key": "id",
                        "value": cohort.pk,
                        "operator": "not_in",
                        "type": "cohort",
                    }
                ]
                self.team.save()

                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.an_hour_ago,
                    team_id=self.team.id,
                )
                # self.create_event(user_one, self.base_time, team=self.team)
                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                    team_id=self.team.id,
                )
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.an_hour_ago,
                    team_id=self.team.id,
                )
                # self.create_event(user_two, self.base_time, team=self.team)
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                    team_id=self.team.id,
                )

                self._assert_query_matches_session_ids(
                    {
                        "filter_test_accounts": True,
                    },
                    [session_id_one],
                )
