import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    HogQLFilters,
    HogQLQueryModifiers,
    QueryTiming,
    SessionPropertyFilter,
)

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import (
    execute_hogql_query_with_timings,
    pretty_print_in_tests,
    pretty_print_response_in_tests,
)

from posthog.errors import InternalCHQueryError
from posthog.models import Cohort
from posthog.models.cohort.util import recalculate_cohortpeople
from posthog.models.exchange_rate.currencies import SUPPORTED_CURRENCY_CODES
from posthog.models.utils import UUIDT, uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME


class TestQuery(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_random_events(self) -> str:
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        _create_person(
            properties={"sneaky_mail": "tim@posthog.com", "random_uuid": random_uuid},
            team=self.team,
            distinct_ids=["bla"],
            is_identified=True,
        )
        flush_persons_and_events()
        for index in range(2):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={
                    "random_prop": "don't include",
                    "random_uuid": random_uuid,
                    "index": index,
                },
            )
        flush_persons_and_events()
        return random_uuid

    def test_extended_query_time(self):
        self.assertEqual(HOGQL_INCREASED_MAX_EXECUTION_TIME, 600)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query(self):
        with freeze_time("2020-01-10"):
            random_uuid = self._create_random_events()

            response = execute_hogql_query(
                "select count(), event from events where properties.random_uuid = {random_uuid} group by event",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results, [(2, "random event")])

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_subquery(self):
        with freeze_time("2020-01-10"):
            random_uuid = self._create_random_events()

            response = execute_hogql_query(
                "select cnt, event from (select count() as cnt, event from events where properties.random_uuid = {random_uuid} group by event) group by cnt, event",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results, [(2, "random event")])

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_subquery_alias(self):
        with freeze_time("2020-01-10"):
            random_uuid = self._create_random_events()

            response = execute_hogql_query(
                "select cnt, event from (select count(*) as cnt, event from events where properties.random_uuid = {random_uuid} group by event) as c group by cnt, event",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results, [(2, "random event")])

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_distinct(self):
        with freeze_time("2020-01-10"):
            random_uuid = self._create_random_events()

            response = execute_hogql_query(
                "select distinct properties.sneaky_mail from persons where properties.random_uuid = {random_uuid}",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results, [("tim@posthog.com",)])

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_person_distinct_ids(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            response = execute_hogql_query(
                f"select distinct person_id, distinct_id from person_distinct_ids",
                self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertTrue(len(response.results) > 0)

    def test_query_timings(self):
        with freeze_time("2020-01-10"):
            random_uuid = self._create_random_events()
            response = execute_hogql_query_with_timings(
                "select count(), event from events where properties.random_uuid = {random_uuid} group by event",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
                pretty=False,
            )
            assert response.timings is not None
            assert isinstance(response.timings, list)
            assert len(response.timings) > 0
            assert isinstance(response.timings[0], QueryTiming)
            self.assertEqual(response.timings[-1].k, ".")

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_joins_simple(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                """
                SELECT event, timestamp, pdi.distinct_id, p.id, p.properties.sneaky_mail
                FROM events e
                LEFT JOIN person_distinct_ids pdi
                ON pdi.distinct_id = e.distinct_id
                LEFT JOIN persons p
                ON p.id = pdi.person_id
                """,
                self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][4], "tim@posthog.com")

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_joins_pdi(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                """
                    SELECT event, timestamp, pdi.person_id from events e
                    INNER JOIN (
                        SELECT distinct_id,
                               argMax(person_id, version) as person_id
                          FROM raw_person_distinct_ids
                         GROUP BY distinct_id
                        HAVING argMax(is_deleted, version) = 0
                       ) AS pdi
                    ON e.distinct_id = pdi.distinct_id
                    """,
                self.team,
                pretty=False,
            )

            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertTrue(len(response.results) > 0)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_joins_events_pdi(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, timestamp, pdi.distinct_id, pdi.person_id FROM events LIMIT 10",
                self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], UUID("00000000-0000-4000-8000-000000000000"))

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_joins_events_e_pdi(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, e.timestamp, e.pdi.distinct_id, pdi.person_id FROM events e LIMIT 10",
                self.team,
                pretty=False,
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, e.timestamp, e.pdi.distinct_id, pdi.person_id FROM events AS e LIMIT 10",
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], UUID("00000000-0000-4000-8000-000000000000"))

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_joins_pdi_persons(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT pdi.distinct_id, pdi.person.created_at FROM person_distinct_ids pdi LIMIT 10",
                self.team,
                pretty=False,
            )
            self.assertEqual(
                response.hogql,
                "SELECT pdi.distinct_id, pdi.person.created_at FROM person_distinct_ids AS pdi LIMIT 10",
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "bla")
            self.assertEqual(
                response.results[0][1],
                datetime.datetime(2020, 1, 10, 0, 0, tzinfo=datetime.UTC),
            )

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_joins_pdi_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT pdi.distinct_id, pdi.person.properties.sneaky_mail FROM person_distinct_ids pdi LIMIT 10",
                self.team,
                pretty=False,
            )
            self.assertEqual(
                response.hogql,
                "SELECT pdi.distinct_id, pdi.person.properties.sneaky_mail FROM person_distinct_ids AS pdi LIMIT 10",
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "bla")
            self.assertEqual(response.results[0][1], "tim@posthog.com")

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_joins_events_pdi_person(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, timestamp, pdi.distinct_id, pdi.person.id FROM events LIMIT 10",
                self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], UUID("00000000-0000-4000-8000-000000000000"))

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_query_joins_events_pdi_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, timestamp, pdi.distinct_id, pdi.person.properties.sneaky_mail FROM events LIMIT 10",
                self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], "tim@posthog.com")

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_joins_events_pdi_e_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, e.timestamp, pdi.distinct_id, e.pdi.person.properties.sneaky_mail FROM events e LIMIT 10",
                self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], "tim@posthog.com")

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_joins_events_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, e.timestamp, e.pdi.person.properties.sneaky_mail FROM events e LIMIT 10",
                self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "tim@posthog.com")

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_joins_events_person_properties_in_aggregration(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            response = execute_hogql_query(
                "SELECT s.pdi.person.properties.sneaky_mail, count() FROM events s GROUP BY s.pdi.person.properties.sneaky_mail LIMIT 10",
                self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "tim@posthog.com")

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_select_person_on_events(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            response = execute_hogql_query(
                "SELECT poe.properties.sneaky_mail, count() FROM events s GROUP BY poe.properties.sneaky_mail LIMIT 10",
                self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "tim@posthog.com")

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_query_select_person_with_joins_without_poe(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, timestamp, person.id, person.properties.sneaky_mail FROM events LIMIT 10",
                self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], UUID("00000000-0000-4000-8000-000000000000"))
            self.assertEqual(response.results[0][3], "tim@posthog.com")

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_query_select_person_with_poe_without_joins(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, timestamp, person.id, person.properties.sneaky_mail FROM events LIMIT 10",
                self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], UUID("00000000-0000-4000-8000-000000000000"))
            self.assertEqual(response.results[0][3], "tim@posthog.com")

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_prop_cohort_basic(self):
        with freeze_time("2020-01-10"):
            _create_person(
                distinct_ids=["some_other_id"],
                team_id=self.team.pk,
                properties={"$some_prop": "something"},
            )
            _create_person(
                distinct_ids=["some_id"],
                team_id=self.team.pk,
                properties={"$some_prop": "something", "$another_prop": "something"},
            )
            _create_person(distinct_ids=["no_match"], team_id=self.team.pk)
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"attr": "some_val"},
            )
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_other_id",
                properties={"attr": "some_val"},
            )
            cohort = Cohort.objects.create(
                team=self.team,
                groups=[
                    {
                        "properties": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            }
                        ]
                    }
                ],
                name="cohort",
            )
            recalculate_cohortpeople(cohort, pending_version=0, initiating_user_id=None)
            with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
                response = execute_hogql_query(
                    "SELECT event, count() FROM events WHERE {cohort_filter} GROUP BY event",
                    team=self.team,
                    placeholders={
                        "cohort_filter": property_to_expr(
                            {"type": "cohort", "key": "id", "value": cohort.pk},
                            self.team,
                        )
                    },
                    pretty=False,
                )
                assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
                self.assertEqual(response.results, [("$pageview", 2)])

            with override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False):
                response = execute_hogql_query(
                    "SELECT event, count(*) FROM events WHERE {cohort_filter} GROUP BY event",
                    team=self.team,
                    placeholders={
                        "cohort_filter": property_to_expr(
                            {"type": "cohort", "key": "id", "value": cohort.pk},
                            self.team,
                        )
                    },
                    pretty=False,
                )
                assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
                self.assertEqual(response.results, [("$pageview", 2)])

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_prop_cohort_static(self):
        with freeze_time("2020-01-10"):
            _create_person(
                distinct_ids=["some_other_id"],
                team_id=self.team.pk,
                properties={"$some_prop": "something"},
            )
            _create_person(
                distinct_ids=["some_id"],
                team_id=self.team.pk,
                properties={"$some_prop": "something", "$another_prop": "something"},
            )
            _create_person(distinct_ids=["no_match"], team_id=self.team.pk)
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"attr": "some_val"},
            )
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_other_id",
                properties={"attr": "some_val"},
            )
            cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
            cohort.insert_users_by_list(["some_id"])

            with override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False):
                response = execute_hogql_query(
                    "SELECT event, count() FROM events WHERE {cohort_filter} GROUP BY event",
                    team=self.team,
                    placeholders={
                        "cohort_filter": property_to_expr(
                            {"type": "cohort", "key": "id", "value": cohort.pk},
                            self.team,
                        )
                    },
                    pretty=False,
                )
                self.assertEqual(response.results, [("$pageview", 1)])
                assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

            with override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False):
                response = execute_hogql_query(
                    "SELECT event, count(*) FROM events WHERE {cohort_filter} GROUP BY event",
                    team=self.team,
                    placeholders={
                        "cohort_filter": property_to_expr(
                            {"type": "cohort", "key": "id", "value": cohort.pk},
                            self.team,
                        )
                    },
                    pretty=False,
                )
                assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
                self.assertEqual(response.results, [("$pageview", 1)])

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_join_with_property_materialized_session_id(self):
        with freeze_time("2020-01-10"):
            _create_person(
                distinct_ids=["some_id"],
                team_id=self.team.pk,
                properties={"$some_prop": "something"},
            )
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"attr": "some_val", "$session_id": "111"},
            )
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"attr": "some_val", "$session_id": "111"},
            )
            produce_replay_summary(
                distinct_id="some_id",
                session_id="111",
                first_timestamp=timezone.now(),
                team_id=self.team.pk,
                ensure_analytics_event_in_session=False,
            )

            response = execute_hogql_query(
                "select e.event, s.session_id from events e left join session_replay_events s on s.session_id = e.properties.$session_id where e.properties.$session_id is not null limit 10",
                team=self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot
            self.assertEqual(response.results, [("$pageview", "111"), ("$pageview", "111")])

            response = execute_hogql_query(
                "select e.event, s.session_id from session_replay_events s left join events e on e.properties.$session_id = s.session_id where e.properties.$session_id is not null limit 10",
                team=self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot
            self.assertEqual(response.results, [("$pageview", "111"), ("$pageview", "111")])

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_join_with_property_not_materialized(self):
        with freeze_time("2020-01-10"):
            _create_person(
                distinct_ids=["some_id"],
                team_id=self.team.pk,
                properties={"$some_prop": "something"},
            )
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"attr": "some_val", "$$$session_id": "111"},
            )
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"attr": "some_val", "$$$session_id": "111"},
            )
            produce_replay_summary(
                distinct_id="some_id",
                session_id="111",
                first_timestamp=timezone.now(),
                team_id=self.team.pk,
            )

            response = execute_hogql_query(
                "select e.event, s.session_id from events e left join session_replay_events s on s.session_id = e.properties.$$$session_id where e.properties.$$$session_id is not null limit 10",
                team=self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot
            self.assertEqual(response.results, [("$pageview", "111"), ("$pageview", "111")])

            response = execute_hogql_query(
                "select e.event, s.session_id from session_replay_events s left join events e on e.properties.$$$session_id = s.session_id where e.properties.$$$session_id is not null limit 10",
                team=self.team,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot
            self.assertEqual(response.results, [("$pageview", "111"), ("$pageview", "111")])

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_hogql_lambdas(self):
        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            response = execute_hogql_query(
                "SELECT arrayMap(x -> x * 2, [1, 2, 3]), 1",
                team=self.team,
                pretty=False,
            )
            self.assertEqual(response.results, [([2, 4, 6], 1)])
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_hogql_groupby_unnecessary_ifnull(self):
        # https://github.com/PostHog/posthog/issues/23077
        query = """
            select toDate(timestamp) as timestamp, count() as cnt
            from events
            where timestamp >= addDays(today(), -10)
            group by timestamp
            having cnt > 10
            limit 1
        """
        with freeze_time("2025-02-15 22:52:00"):
            response = execute_hogql_query(query, team=self.team, pretty=False)
            self.assertEqual(response.results, [])
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_hogql_unnecessary_ifnull(self):
        # https://github.com/PostHog/posthog/issues/23077
        query = """
            select
                toDate(timestamp) as timestamp,
                JSONExtractInt(properties, 'field') as json_int
            from events
            where timestamp >= addDays(today(), -10) and json_int = 17
            limit 1
        """
        with freeze_time("2025-02-15 22:52:00"):
            response = execute_hogql_query(query, team=self.team, pretty=False)
            self.assertEqual(response.results, [])
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_hogql_proper_ifnull(self):
        # latest_os_version is Nullable, splitByChar does not access Nullable argument
        query = """
            WITH latest_events AS (
                SELECT distinct_id, argMax(properties.$os_version, timestamp) AS latest_os_version
                FROM events
                WHERE properties.$os = 'iOS' AND timestamp >= now() - INTERVAL 30 DAY GROUP BY distinct_id),
            major_versions AS (
                SELECT distinct_id, latest_os_version, splitByChar('.', ifNull(latest_os_version, ''))[1] AS major_version
                FROM latest_events)
            SELECT major_version, count() AS user_count, round(100 * count() / sum(count()) OVER (), 2) AS percentage
            FROM major_versions
            WHERE major_version IN ('17', '18', '26')
            GROUP BY major_version
            ORDER BY major_version
        """
        with freeze_time("2025-02-15 22:52:00"):
            response = execute_hogql_query(query, team=self.team, pretty=False)
            self.assertEqual(response.results, [])
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_hogql_arrays(self):
        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            response = execute_hogql_query(
                "SELECT [1, 2, 3], [10,11,12][1]",
                team=self.team,
                pretty=False,
            )
            # Following SQL tradition, ClickHouse array indexes start at 1, not from zero.
            self.assertEqual(response.results, [([1, 2, 3], 10)])
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_tuple_access(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            # sample pivot table, testing tuple access
            query = """
                select col_a, arrayZip( (sumMap( g.1, g.2 ) as x).1, x.2) as r from (
                select col_a, groupArray( (col_b, col_c) ) as g from
                (
                    SELECT properties.index as col_a,
                           event as col_b,
                           count() as col_c
                      FROM events
                  GROUP BY properties.index,
                           event
                )
                group by col_a)
                group by col_a ORDER BY col_a
            """
            response = execute_hogql_query(
                query,
                team=self.team,
                pretty=False,
            )
            self.assertEqual(
                response.results,
                [("0", [("random event", 1)]), ("1", [("random event", 1)])],
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    def test_null_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            _create_event(
                distinct_id="bla",
                event="empty event",
                team=self.team,
                properties={
                    "empty_string": "",
                    "null": None,
                    "str_zero": "0",
                    "num_zero": 0,
                },
            )

            query = """
                SELECT
                    properties.empty_string,
                    properties.`null`,
                    properties.undefined,
                    properties.str_zero,
                    properties.num_zero
                FROM events
                WHERE events.event='empty event'
            """
            response = execute_hogql_query(
                query,
                team=self.team,
            )
            self.assertEqual(
                response.results,
                [
                    (
                        "",  # empty string
                        None,  # null
                        None,  # undefined
                        "0",  # zero string
                        "0",  # zero number (not typecast)
                    )
                ],
            )

    def test_window_functions_simple(self):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        for person in range(5):
            distinct_id = f"person_{person}_{random_uuid}"
            with freeze_time("2020-01-10 00:00:00"):
                _create_person(
                    properties={"name": f"Person {person}", "random_uuid": random_uuid},
                    team=self.team,
                    distinct_ids=[distinct_id],
                    is_identified=True,
                )
                _create_event(
                    distinct_id=distinct_id,
                    event="random event",
                    team=self.team,
                    properties={"character": "Luigi"},
                )
                flush_persons_and_events()
            with freeze_time("2020-01-10 00:10:00"):
                _create_event(
                    distinct_id=distinct_id,
                    event="random bla",
                    team=self.team,
                    properties={"character": "Luigi"},
                )
                flush_persons_and_events()
            with freeze_time("2020-01-10 00:20:00"):
                _create_event(
                    distinct_id=distinct_id,
                    event="random boo",
                    team=self.team,
                    properties={"character": "Luigi"},
                )
                flush_persons_and_events()

        query = f"""
           select distinct_id,
                  timestamp,
                  event,
                  groupArray(event) OVER (PARTITION BY distinct_id ORDER BY timestamp ASC ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING) AS two_before,
                  groupArray(event) OVER (PARTITION BY distinct_id ORDER BY timestamp ASC ROWS BETWEEN 1 FOLLOWING AND 2 FOLLOWING) AS two_after
             from events
            where timestamp > toDateTime('2020-01-09 00:00:00')
              and distinct_id like '%_{random_uuid}'
         order by distinct_id, timestamp
        """
        response = execute_hogql_query(query, team=self.team)

        expected = []
        for person in range(5):
            expected += [
                (
                    f"person_{person}_{random_uuid}",
                    datetime.datetime(2020, 1, 10, 00, 00, 00, tzinfo=ZoneInfo("UTC")),
                    "random event",
                    [],
                    ["random bla", "random boo"],
                ),
                (
                    f"person_{person}_{random_uuid}",
                    datetime.datetime(2020, 1, 10, 00, 10, 00, tzinfo=ZoneInfo("UTC")),
                    "random bla",
                    ["random event"],
                    ["random boo"],
                ),
                (
                    f"person_{person}_{random_uuid}",
                    datetime.datetime(2020, 1, 10, 00, 20, 00, tzinfo=ZoneInfo("UTC")),
                    "random boo",
                    ["random event", "random bla"],
                    [],
                ),
            ]
        self.assertEqual(response.results, expected)

    def test_window_functions_with_window(self):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        for person in range(5):
            distinct_id = f"person_{person}_{random_uuid}"
            with freeze_time("2020-01-10 00:00:00"):
                _create_person(
                    properties={"name": f"Person {person}", "random_uuid": random_uuid},
                    team=self.team,
                    distinct_ids=[distinct_id],
                    is_identified=True,
                )
                _create_event(
                    distinct_id=distinct_id,
                    event="random event",
                    team=self.team,
                    properties={"character": "Luigi"},
                )
                flush_persons_and_events()
            with freeze_time("2020-01-10 00:10:00"):
                _create_event(
                    distinct_id=distinct_id,
                    event="random bla",
                    team=self.team,
                    properties={"character": "Luigi"},
                )
                flush_persons_and_events()
            with freeze_time("2020-01-10 00:20:00"):
                _create_event(
                    distinct_id=distinct_id,
                    event="random boo",
                    team=self.team,
                    properties={"character": "Luigi"},
                )
                flush_persons_and_events()

        query = f"""
           select distinct_id,
                  timestamp,
                  event,
                  groupArray(event) OVER w1 AS two_before,
                  groupArray(event) OVER w2 AS two_after,
                  row_number() OVER w1 AS rn_1,
                  row_number() OVER w2 AS rn_2,
                  first_value(event) OVER w1 AS first_value_1,
                  last_value(event) OVER w1 AS last_value_1,
                  first_value(event) OVER w2 AS first_value_2,
                  last_value(event) OVER w2 AS last_value_2,
                  rank() OVER w1 AS rank_1,
                  dense_rank() OVER w2 AS rank_2
             from events
            where timestamp > toDateTime('2020-01-09 00:00:00')
              and distinct_id like '%_{random_uuid}'
           window w1 as (PARTITION BY distinct_id ORDER BY timestamp ASC ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING),
                  w2 as (PARTITION BY distinct_id ORDER BY timestamp ASC ROWS BETWEEN 1 FOLLOWING AND 2 FOLLOWING)
         order by distinct_id, timestamp
        """
        response = execute_hogql_query(query, team=self.team)

        expected = []
        for person in range(5):
            expected += [
                (
                    f"person_{person}_{random_uuid}",
                    datetime.datetime(2020, 1, 10, 00, 00, 00, tzinfo=ZoneInfo("UTC")),
                    "random event",
                    [],
                    ["random bla", "random boo"],
                    1,
                    1,
                    "",
                    "",
                    "random bla",
                    "random boo",
                    1,
                    1,
                ),
                (
                    f"person_{person}_{random_uuid}",
                    datetime.datetime(2020, 1, 10, 00, 10, 00, tzinfo=ZoneInfo("UTC")),
                    "random bla",
                    ["random event"],
                    ["random boo"],
                    2,
                    2,
                    "random event",
                    "random event",
                    "random boo",
                    "random boo",
                    2,
                    2,
                ),
                (
                    f"person_{person}_{random_uuid}",
                    datetime.datetime(2020, 1, 10, 00, 20, 00, tzinfo=ZoneInfo("UTC")),
                    "random boo",
                    ["random event", "random bla"],
                    [],
                    3,
                    3,
                    "random event",
                    "random bla",
                    "",
                    "",
                    3,
                    3,
                ),
            ]
        self.assertEqual(response.results, expected)

    def test_between_operators(self):
        cases = [
            ("5 between 1 and 10", 1),
            ("1 between 1 and 10", 1),
            ("10 between 1 and 10", 1),
            ("0 between 1 and 10", 0),
            ("11 between 1 and 10", 0),
            ("5 not between 1 and 10", 0),
            ("0 not between 1 and 10", 1),
            ("11 not between 1 and 10", 1),
            ("10 not between 1 and 10", 0),
            ("null between 1 and 10", 0),
            ("5 between null and 10", 0),
            ("5 between 1 and null", 0),
        ]
        for expr, expected in cases:
            q = f"select {expr}"
            response = execute_hogql_query(q, team=self.team)
            self.assertEqual(response.results, [(expected,)], [q, response.clickhouse])

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_with_pivot_table_1_level(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            # sample pivot table, testing tuple access
            query = """
                 WITH PIVOT_TABLE_COL_ABC AS (
                             SELECT properties.index as col_a,
                                    event as col_b,
                                    count() as col_c
                               FROM events
                           GROUP BY properties.index,
                                    event
                          ),
                          PIVOT_FUNCTION_1 AS (
                              select col_a, groupArray( (col_b, col_c) ) as g from
                                PIVOT_TABLE_COL_ABC
                                group by col_a
                          ),
                          PIVOT_FUNCTION_2 AS (
                              select col_a, arrayZip( (sumMap( g.1, g.2 ) as x).1, x.2) as r from
                              PIVOT_FUNCTION_1
                              group by col_a
                          )
                   SELECT *
                     FROM PIVOT_FUNCTION_2
                 ORDER BY col_a
            """
            response = execute_hogql_query(
                query,
                team=self.team,
                pretty=False,
            )
            self.assertEqual(
                response.results,
                [("0", [("random event", 1)]), ("1", [("random event", 1)])],
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_with_pivot_table_2_levels(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            # sample pivot table, testing tuple access
            query = """
                 WITH PIVOT_TABLE_COL_ABC AS (
                             SELECT properties.index as col_a,
                                    event as col_b,
                                    count() as col_c
                               FROM events
                           GROUP BY properties.index,
                                    event
                          ),
                          PIVOT_FUNCTION_1 AS (
                              select col_a, groupArray( (col_b, col_c) ) as g from
                                PIVOT_TABLE_COL_ABC
                                group by col_a
                          ),
                          PIVOT_FUNCTION_2 AS (
                              select col_a, arrayZip( (sumMap( g.1, g.2 ) as x).1, x.2) as r from
                              PIVOT_FUNCTION_1
                              group by col_a
                          ),
                          final as (select * from PIVOT_FUNCTION_2)
                   SELECT *
                     FROM final
                 ORDER BY col_a
            """
            response = execute_hogql_query(
                query,
                team=self.team,
                pretty=False,
            )
            self.assertEqual(
                response.results,
                [("0", [("random event", 1)]), ("1", [("random event", 1)])],
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    def test_property_access_with_arrays(self):
        with freeze_time("2020-01-10"):
            random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
            _create_person(team=self.team, distinct_ids=[f"P{random_uuid}"], is_identified=True)
            _create_event(
                distinct_id=f"P{random_uuid}",
                event="big event",
                team=self.team,
                properties={
                    "string": random_uuid,
                    "array_str": [random_uuid],
                    "obj_array": {"id": [random_uuid]},
                    "array_array_str": [[random_uuid]],
                    "array_obj": [{"id": random_uuid}],
                    "array_obj_array": [{"id": [random_uuid]}],
                    "array_obj_array_obj": [{"id": [{"id": random_uuid}]}],
                },
            )
            flush_persons_and_events()

            alternatives = [
                "properties.string",
                "properties.array_str.1",
                "properties.array_str[1]",
                "properties.obj_array.id.1",
                "properties.obj_array.id[1]",
                "properties.array_array_str.1.1",
                "properties.array_array_str[1][1]",
                "properties.array_obj_array.1.id.1",
                "properties.array_obj_array[1]['id'][1]",
                "properties.array_obj_array_obj.1.id.1.id",
                "properties.array_obj_array_obj[1].id[1].id",
                "properties.array_obj_array_obj[1]['id'][1]['id']",
                "properties.array_obj.1.id",
                "properties.array_obj[1].id",
            ]
            columns = ",".join(alternatives)
            query = f"SELECT {columns} FROM events WHERE properties.string = '{random_uuid}'"
            response = execute_hogql_query(
                query,
                team=self.team,
                pretty=False,
            )
            self.assertEqual(
                f"SELECT "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '') AS string, "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s, %(hogql_val_2)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_3)s, %(hogql_val_4)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_5)s, %(hogql_val_6)s, %(hogql_val_7)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_8)s, %(hogql_val_9)s, %(hogql_val_10)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_11)s, %(hogql_val_12)s, %(hogql_val_13)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_14)s, %(hogql_val_15)s, %(hogql_val_16)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_17)s, %(hogql_val_18)s, %(hogql_val_19)s, %(hogql_val_20)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_21)s, %(hogql_val_22)s, %(hogql_val_23)s, %(hogql_val_24)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_25)s, %(hogql_val_26)s, %(hogql_val_27)s, %(hogql_val_28)s, %(hogql_val_29)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_30)s, %(hogql_val_31)s, %(hogql_val_32)s, %(hogql_val_33)s, %(hogql_val_34)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_35)s, %(hogql_val_36)s, %(hogql_val_37)s, %(hogql_val_38)s, %(hogql_val_39)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_40)s, %(hogql_val_41)s, %(hogql_val_42)s), ''), 'null'), '^\"|\"$', ''), "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_43)s, %(hogql_val_44)s, %(hogql_val_45)s), ''), 'null'), '^\"|\"$', '') "
                f"FROM events "
                f"WHERE and(equals(events.team_id, {self.team.pk}), ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_46)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_47)s), 0)) "
                f"LIMIT 100 "
                f"SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, output_format_json_quote_64bit_integers=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1",
                response.clickhouse,
            )
            self.assertEqual(response.results[0], tuple(random_uuid for x in alternatives))

    def test_property_access_with_arrays_zero_index_error(self):
        query = f"SELECT properties.something[0] FROM events"
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(query, team=self.team)
        self.assertEqual(str(e.exception), "SQL indexes start from one, not from zero. E.g: array[1]")

        query = f"SELECT properties.something.0 FROM events"
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(query, team=self.team)
        self.assertEqual(str(e.exception), "SQL indexes start from one, not from zero. E.g: array.1")

    def test_time_window_functions(self):
        query = """
            SELECT
                tumble(toDateTime('2020-01-01'), toIntervalDay('1')),
                tumbleStart(toDateTime('2020-01-01'), toIntervalDay('1')),
                tumbleEnd(toDateTime('2020-01-01'), toIntervalDay('1')),
                hop(toDateTime('2020-01-01'), toIntervalDay('1'), toIntervalDay('2')),
                hopStart(toDateTime('2020-01-01'), toIntervalDay('1'), toIntervalDay('2')),
                hopEnd(toDateTime('2020-01-01'), toIntervalDay('1'), toIntervalDay('2'))
        """

        response = execute_hogql_query(
            query,
            team=self.team,
        )

        self.assertEqual(
            response.results,
            [
                (
                    (
                        datetime.datetime(2020, 1, 1, 0, 0, tzinfo=datetime.UTC),
                        datetime.datetime(2020, 1, 2, 0, 0, tzinfo=datetime.UTC),
                    ),
                    datetime.datetime(2020, 1, 1, 0, 0, tzinfo=datetime.UTC),
                    datetime.datetime(2020, 1, 2, 0, 0, tzinfo=datetime.UTC),
                    (
                        datetime.datetime(2019, 12, 31, 0, 0, tzinfo=datetime.UTC),
                        datetime.datetime(2020, 1, 2, 0, 0, tzinfo=datetime.UTC),
                    ),
                    datetime.datetime(2019, 12, 31, 0, 0, tzinfo=datetime.UTC),
                    datetime.datetime(2020, 1, 2, 0, 0, tzinfo=datetime.UTC),
                )
            ],
        )

    def test_null_equality(self):
        expected = [
            # left op right (result 0=False 1=True)
            ("null", "=", "2", 0),
            ("2", "=", "null", 0),
            ("3", "=", "4", 0),
            ("3", "=", "3", 1),
            ("null", "=", "null", 1),
            ("null", "!=", "2", 1),
            ("2", "!=", "null", 1),
            ("3", "!=", "4", 1),
            ("3", "!=", "3", 0),
            ("null", "!=", "null", 0),
            ("null", "<", "2", 0),
            ("2", "<", "null", 0),
            ("3", "<", "4", 1),
            ("3", "<", "3", 0),
            ("null", "<", "null", 0),
            ("null", "<=", "2", 0),
            ("2", "<=", "null", 0),
            ("3", "<=", "4", 1),
            ("3", "<=", "3", 1),
            ("3", "<=", "2", 0),
            ("null", "<=", "null", 0),
            ("null", ">", "2", 0),
            ("2", ">", "null", 0),
            ("4", ">", "3", 1),
            ("3", ">", "3", 0),
            ("null", ">", "null", 0),
            ("null", ">=", "2", 0),
            ("2", ">=", "null", 0),
            ("4", ">=", "3", 1),
            ("3", ">=", "3", 1),
            ("2", ">=", "3", 0),
            ("null", ">=", "null", 0),
            ("null", "like", "'2'", 0),
            ("'2'", "like", "null", 0),
            ("'3'", "like", "'4'", 0),
            ("'3'", "like", "'3'", 1),
            ("null", "like", "null", 1),
            ("null", "not like", "'2'", 1),
            ("'2'", "not like", "null", 1),
            ("'3'", "not like", "'4'", 1),
            ("'3'", "not like", "'3'", 0),
            ("null", "not like", "null", 0),
            ("null", "ilike", "'2'", 0),
            ("'2'", "ilike", "null", 0),
            ("'3'", "ilike", "'4'", 0),
            ("'3'", "ilike", "'3'", 1),
            ("null", "ilike", "null", 1),
            ("null", "not ilike", "'2'", 1),
            ("'2'", "not ilike", "null", 1),
            ("'3'", "not ilike", "'4'", 1),
            ("'3'", "not ilike", "'3'", 0),
            ("null", "not ilike", "null", 0),
            ("null", "=~", "'2'", 0),
            ("'2'", "=~", "null", 0),
            ("'3'", "=~", "'4'", 0),
            ("'3'", "=~", "'3'", 1),
            ("null", "=~", "null", 1),
            ("null", "!~", "'2'", 1),
            ("'2'", "!~", "null", 1),
            ("'3'", "!~", "'4'", 1),
            ("'3'", "!~", "'3'", 0),
            ("null", "!~", "null", 0),
            ("null", "=~*", "'2'", 0),
            ("'2'", "=~*", "null", 0),
            ("'3'", "=~*", "'4'", 0),
            ("'3'", "=~*", "'3'", 1),
            ("null", "=~*", "null", 1),
            ("null", "!~*", "'2'", 1),
            ("'2'", "!~*", "null", 1),
            ("'3'", "!~*", "'4'", 1),
            ("'3'", "!~*", "'3'", 0),
            ("null", "!~*", "null", 0),
        ]

        for a, op, b, res in expected:
            # works when selecting directly
            query = f"select {a} {op} {b}"
            response = execute_hogql_query(query, team=self.team)
            self.assertEqual(response.results, [(res,)], [query, response.clickhouse])

            # works when selecting via a subquery
            query = f"select a {op} b from (select {a} as a, {b} as b)"
            response = execute_hogql_query(query, team=self.team)
            self.assertEqual(response.results, [(res,)], [query, response.clickhouse])

            # works when selecting via a subquery
            query = f"select {a} {op} b from (select {b} as b)"
            response = execute_hogql_query(query, team=self.team)
            self.assertEqual(response.results, [(res,)], [query, response.clickhouse])

            # works when selecting via a subquery
            query = f"select a {op} {b} from (select {a} as a)"
            response = execute_hogql_query(query, team=self.team)
            self.assertEqual(response.results, [(res,)], [query, response.clickhouse])

    def test_regex_functions(self):
        query = """
            SELECT
                'kala' ~ '.*',
                'kala' =~ '.*',
                'kala' !~ '.*',
                'kala' =~ 'a',
                'kala' !~ 'a',
                'kala' =~ 'A',
                'kala' !~ 'A',
                'kala' ~* 'A',
                'kala' =~* 'A',
                'kala' !~* 'A'
        """

        response = execute_hogql_query(
            query,
            team=self.team,
            pretty=False,
        )

        self.assertEqual(
            response.results,
            [(True, True, False, True, False, False, True, True, True, False)],
        )

    def test_nullish_coalescing(self):
        query = """
            SELECT
                null ?? 1,
                null ?? null ?? 2,
                3 ?? null,
                null ?? 'string',
                1 + (null ?? 2) + 3,
                1 + null ?? 2 + 3,
                10 ?? true ? 20 : 30,
                10 ?? 5 + 10
        """

        response = execute_hogql_query(
            query,
            team=self.team,
        )

        self.assertEqual(
            response.results,
            [(1, 2, 3, "string", 6, 5, 20, 10)],
        )

    def test_numbers_table(self):
        query = "SELECT number from numbers(1, 4)"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(
            response.results,
            [
                (1,),
                (2,),
                (3,),
                (4,),
            ],
        )

        query = "SELECT * from numbers(1, 4)"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(
            response.results,
            [
                (1,),
                (2,),
                (3,),
                (4,),
            ],
        )

        query = "SELECT number from numbers(4)"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(
            response.results,
            [
                (0,),
                (1,),
                (2,),
                (3,),
            ],
        )

        query = "SELECT number from numbers(2 + 2)"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(
            response.results,
            [
                (0,),
                (1,),
                (2,),
                (3,),
            ],
        )

        query = "SELECT number + number + 1 from numbers(2 + 2)"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(
            response.results,
            [
                (1,),
                (3,),
                (5,),
                (7,),
            ],
        )

        query = f"SELECT number from numbers"
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(query, team=self.team)
        self.assertEqual(str(e.exception), "Table function 'numbers' requires arguments")

        query = f"SELECT number from numbers()"
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(query, team=self.team)
        self.assertEqual(str(e.exception), "Table function 'numbers' requires at least 1 argument")

        query = f"SELECT number from numbers(1,2,3)"
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(query, team=self.team)
        self.assertEqual(str(e.exception), "Table function 'numbers' requires at most 2 arguments")

        query = "SELECT number from numbers(2 + ifNull((select 2), 1000))"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(
            response.results,
            [
                (0,),
                (1,),
                (2,),
                (3,),
            ],
        )

        query = "SELECT number from numbers(assumeNotNull(dateDiff('day', toStartOfDay(toDateTime('2011-12-31 00:00:00')), toDateTime('2012-01-14 23:59:59'))))"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(
            response.results,
            [
                (0,),
                (1,),
                (2,),
                (3,),
                (4,),
                (5,),
                (6,),
                (7,),
                (8,),
                (9,),
                (10,),
                (11,),
                (12,),
                (13,),
            ],
        )

    def test_events_table_error_if_function(self):
        query = "SELECT * from events(1, 4)"
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(query, team=self.team)
        self.assertEqual(str(e.exception), "Table 'events' does not accept arguments")

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_hogql_query_filters(self):
        with freeze_time("2020-01-10"):
            random_uuid = self._create_random_events()
            for i in range(10):
                _create_event(
                    distinct_id=random_uuid,
                    event="random event",
                    team=self.team,
                    properties={"index": i, "user_key": random_uuid},
                )
            query = "SELECT event, distinct_id from events WHERE distinct_id={distinct_id} and {filters}"
            filters = HogQLFilters(
                properties=[EventPropertyFilter(key="index", operator="exact", value="4", type="event")]
            )
            placeholders = {"distinct_id": ast.Constant(value=random_uuid)}
            response = execute_hogql_query(
                query,
                team=self.team,
                filters=filters,
                placeholders=placeholders,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot
            self.assertEqual(len(response.results), 1)

            filters.dateRange = DateRange(date_from="2020-01-01", date_to="2020-01-02")
            response = execute_hogql_query(
                query,
                team=self.team,
                filters=filters,
                placeholders=placeholders,
                pretty=False,
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot
            self.assertEqual(len(response.results), 0)

            filters.dateRange = DateRange(date_from="2020-01-01", date_to="2020-02-02")
            response = execute_hogql_query(query, team=self.team, filters=filters, placeholders=placeholders)
            self.assertEqual(len(response.results), 1)

    def test_clickhouse_timestamp_handling(self):
        query = """
            SELECT
                issue_id AS id,
                count(DISTINCT uuid) AS occurrences,
                count(DISTINCT nullIf($session_id, '')) AS sessions,
                count(DISTINCT distinct_id) AS users,
                max(timestamp) AS last_seen,
                min(timestamp) AS first_seen,
                reverse(arrayMap(x -> countEqual(groupArray(dateDiff('hour', toStartOfHour(timestamp), toStartOfHour(now()))), x), range(24))) AS volumeDay,
                reverse(arrayMap(x -> countEqual(groupArray(dateDiff('day', toStartOfDay(timestamp), toStartOfDay(now()))), x), range(31))) AS volumeMonth,
                reverse(arrayMap(x -> countEqual(groupArray(dateDiff('hour', toStartOfHour(timestamp), toStartOfHour(now()))), x), range(168))) AS customVolume
            FROM
                events
            WHERE
                and(
                    equals(event, '$exception'),
                    isNotNull(issue_id),
                    or(
                        and(greater(timestamp, toDateTime('2025-02-10 23:53:03.175952+02:30')), less(timestamp, toDateTime('2025-02-11 23:53'))),
                        and(greater(timestamp, toDateTime('2025-02-12 23:53:03')), less(timestamp, toDateTime('2025-02-13 23:53:03.175952')))
                    )
                )
            GROUP BY
                issue_id
            ORDER BY
                occurrences DESC
            LIMIT 51
            OFFSET 0
        """

        with freeze_time("2025-02-15 22:52:00"):
            response = execute_hogql_query(query, team=self.team, pretty=False)
            self.assertEqual(response.results, [])
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    def test_hogql_query_filters_empty_true(self):
        query = "SELECT event from events where {filters}"
        response = execute_hogql_query(
            query,
            team=self.team,
            pretty=False,
        )
        self.assertEqual(response.hogql, "SELECT event FROM events WHERE true LIMIT 100")

    def test_hogql_query_filters_double_error(self):
        query = "SELECT event from events where {filters}"
        with self.assertRaises(ValueError) as e:
            execute_hogql_query(
                query,
                team=self.team,
                filters=HogQLFilters(),
                placeholders={"filters": ast.Constant(value=True)},
            )
        self.assertEqual(
            str(e.exception),
            "Query contains 'filters' both as placeholder and as a query parameter.",
        )

    def test_hogql_query_filters_alias(self):
        with freeze_time("2020-01-10"):
            random_uuid = self._create_random_events()
            query = "SELECT event, distinct_id from events e WHERE {filters}"
            filters = HogQLFilters(
                properties=[
                    EventPropertyFilter(
                        key="random_uuid",
                        operator="exact",
                        value=random_uuid,
                        type="event",
                    )
                ]
            )
            response = execute_hogql_query(
                query,
                team=self.team,
                filters=filters,
                pretty=False,
            )
            self.assertEqual(
                response.hogql,
                f"SELECT event, distinct_id FROM events AS e WHERE equals(properties.random_uuid, '{random_uuid}') LIMIT 100",
            )
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            self.assertEqual(len(response.results), 2)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_hogql_union_all_limits(self):
        query = "SELECT event FROM events UNION ALL SELECT event FROM events"
        response = execute_hogql_query(
            query,
            team=self.team,
            pretty=False,
        )
        self.assertEqual(
            response.hogql,
            f"SELECT event FROM events LIMIT 100 UNION ALL SELECT event FROM events LIMIT 100",
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_hogql_query_session_filters(self):
        with freeze_time("2024-07-05"):
            s1 = str(uuid7("2024-07-03", 42))
            s2 = str(uuid7("2024-07-04", 43))
            _create_event(
                distinct_id=s1,
                event="$pageview",
                team=self.team,
                properties={"$session_id": s1, "$current_url": "https://example.com/1"},
            )
            _create_event(
                distinct_id=s2,
                event="$pageview",
                team=self.team,
                properties={"$session_id": s2, "$current_url": "https://example.com/2"},
            )
            query = "SELECT session_id, $entry_current_url from sessions WHERE {filters}"
            filters = HogQLFilters(
                properties=[
                    SessionPropertyFilter(key="$entry_current_url", operator="exact", value="https://example.com/1")
                ]
            )
            response = execute_hogql_query(
                query,
                team=self.team,
                filters=filters,
                placeholders={},
                pretty=False,
            )
            assert response.hogql is not None
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot
            self.assertEqual(response.results, [(s1, "https://example.com/1")])

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_hogql_query_filters_session_date_range(self):
        with freeze_time("2024-07-05"):
            s1 = str(uuid7("2024-07-03", 42))
            s2 = str(uuid7("2024-07-05", 43))
            _create_event(
                distinct_id=s1,
                event="$pageview",
                team=self.team,
                properties={"$session_id": s1, "$current_url": "https://example.com/1"},
                timestamp="2024-07-03T00:00:00Z",
            )
            _create_event(
                distinct_id=s2,
                event="$pageview",
                team=self.team,
                properties={"$session_id": s2, "$current_url": "https://example.com/2"},
                timestamp="2024-07-05T00:00:00Z",
            )
            query = "SELECT session_id, $entry_current_url from sessions WHERE {filters}"
            filters = HogQLFilters(dateRange=DateRange(date_from="2024-07-04", date_to="2024-07-06"))
            response = execute_hogql_query(
                query,
                team=self.team,
                filters=filters,
                placeholders={},
                pretty=False,
            )
            assert response.hogql is not None
            assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
            assert pretty_print_in_tests(response.hogql, self.team.pk) == self.snapshot
            self.assertEqual(response.results, [(s2, "https://example.com/2")])

    def test_events_sessions_table(self):
        with freeze_time("2020-01-10 12:00:00"):
            random_uuid = self._create_random_events()
            session_id = str(uuid7())

        with freeze_time("2020-01-10 12:10:00"):
            _create_event(
                distinct_id=random_uuid,
                event="random event",
                team=self.team,
                properties={"$session_id": session_id},
            )
        with freeze_time("2020-01-10 12:20:00"):
            _create_event(
                distinct_id=random_uuid,
                event="random event",
                team=self.team,
                properties={"$session_id": session_id},
            )

        query = "SELECT session.session_id, session.$session_duration from events WHERE distinct_id={distinct_id} order by timestamp"
        response = execute_hogql_query(
            query, team=self.team, placeholders={"distinct_id": ast.Constant(value=random_uuid)}
        )
        assert response.results == [
            (session_id, 600),
            (session_id, 600),
        ]

    def test_db_created_once(self):
        # This test will start failing when we cache the DB creation - that's fine, just delete or change it.
        # In the ideal future, most queries will not need to create the DB.
        # In the present (your past), this test was added because we were creating it twice per query.
        query = "SELECT 1"
        with patch("posthog.hogql.database.database.Database.create_for") as create_for_mock:
            execute_hogql_query(query, team=self.team)
            create_for_mock.assert_called_once()

    def test_sortable_semver(self):
        query = "SELECT arrayJoin(['0.0.0.0.1000', '0.9', '0.2354.2', '1.0.0', '1.1.0', '1.2.0', '1.9.233434.10', '1.10.0', '1.1000.0', '2.0.0', '2.2.0.betabac', '2.2.1']) AS semver ORDER BY sortableSemVer(semver) DESC"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(
            response.results,
            [
                ("2.2.1",),
                ("2.2.0.betabac",),
                ("2.0.0",),
                ("1.1000.0",),
                ("1.10.0",),
                ("1.9.233434.10",),
                ("1.2.0",),
                ("1.1.0",),
                ("1.0.0",),
                ("0.2354.2",),
                ("0.9",),
                ("0.0.0.0.1000",),
            ],
        )

    def test_sortable_semver_output(self):
        query = "SELECT sortableSemVer('1.2.3.4.15bac.16')"
        response = execute_hogql_query(query, team=self.team)

        # Ignore everything after string, return as array of ints
        self.assertEqual(response.results, [([1, 2, 3, 4, 15],)])

    def test_exchange_rate_table(self):
        query = "SELECT DISTINCT currency FROM exchange_rate LIMIT 500"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(len(response.results), len(SUPPORTED_CURRENCY_CODES))

    def test_currency_conversion(self):
        query = "SELECT convertCurrency('USD', 'EUR', 100, _toDate('2024-01-01'))"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(response.results, [(Decimal("90.49"),)])

    def test_currency_conversion_with_string_date(self):
        query = "SELECT convertCurrency('USD', 'EUR', 100, '2024-01-01')"
        with self.assertRaises(InternalCHQueryError) as e:
            execute_hogql_query(query, team=self.team)
        assert (
            "Illegal type String of fourth argument of function dictGetOrDefault must be convertible to Int64"
            in str(e.exception)
        )

    def test_currency_conversion_with_bogus_currency_from(self):
        query = "SELECT convertCurrency('BOGUS', 'EUR', 100, _toDate('2024-01-01'))"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(response.results, [(Decimal("0"),)])

    def test_currency_conversion_with_bogus_currency_to(self):
        query = "SELECT convertCurrency('USD', 'BOGUS', 100, _toDate('2024-01-01'))"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(response.results, [(Decimal("0"),)])

    # Returns today's date if no date is provided
    # which will simply use the latest rate from `historical.csv`
    # from 2024-12-31
    def test_currency_conversion_without_date(self):
        query = "SELECT convertCurrency('USD', 'EUR', 100)"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(response.results, [(Decimal("96.21"),)])

    def test_currency_conversion_nested(self):
        query = "SELECT convertCurrency('EUR', 'USD', convertCurrency('USD', 'EUR', 100, _toDate('2020-03-15')), _toDate('2020-03-15'))"
        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(response.results, [(Decimal("100.00"),)])

    def test_currency_conversion_super_nested(self):
        amount = "2123.4308"
        query = """
            SELECT convertCurrency(
                'JPY', 'USD',
                convertCurrency(
                    'GBP', 'JPY',
                    convertCurrency(
                        'EUR', 'GBP',
                        convertCurrency(
                            'USD', 'EUR', {amount}, {date}
                        ), {date}
                    ), {date}
                ), {date}
            )
        """.format(amount=amount, date="_toDate('2020-03-15')")

        response = execute_hogql_query(query, team=self.team)
        self.assertEqual(response.results, [(Decimal(amount),)])

    def test_metadata_handles_lazy_joins(self):
        query = "SELECT events.session.id from events"
        response = execute_hogql_query(query, team=self.team, modifiers=HogQLQueryModifiers(debug=True))
        assert response and response.metadata and response.metadata.ch_table_names
        assert any("sessions" in name for name in response.metadata.ch_table_names)
