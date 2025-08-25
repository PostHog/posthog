import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

from freezegun import freeze_time
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    snapshot_clickhouse_insert_cohortpeople_queries,
    snapshot_clickhouse_queries,
)

from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.schema import PersonsOnEventsMode

from posthog.hogql.constants import MAX_SELECT_COHORT_CALCULATION_LIMIT
from posthog.hogql.hogql import HogQLContext

from posthog.clickhouse.client import sync_execute
from posthog.models.action import Action
from posthog.models.cohort import Cohort
from posthog.models.cohort.sql import GET_COHORTPEOPLE_BY_COHORT_ID
from posthog.models.cohort.util import format_filter_query
from posthog.models.filters import Filter
from posthog.models.organization import Organization
from posthog.models.person import Person
from posthog.models.person.sql import GET_LATEST_PERSON_SQL, GET_PERSON_IDS_BY_FILTER
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.models.team import Team
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.util import PersonPropertiesMode


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name}])
    return action


def get_person_ids_by_cohort_id(
    team_id: int,
    cohort_id: int,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
):
    from posthog.models.property.util import parse_prop_grouped_clauses

    filter = Filter(data={"properties": [{"key": "id", "value": cohort_id, "type": "cohort"}]})
    filter_query, filter_params = parse_prop_grouped_clauses(
        team_id=team_id,
        property_group=filter.property_groups,
        table_name="pdi",
        hogql_context=filter.hogql_context,
    )

    results = sync_execute(
        GET_PERSON_IDS_BY_FILTER.format(
            person_query=GET_LATEST_PERSON_SQL,
            distinct_query=filter_query,
            query="",
            GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(team_id),
            offset="OFFSET %(offset)s" if offset else "",
            limit="ORDER BY _timestamp ASC LIMIT %(limit)s" if limit else "",
        ),
        {**filter_params, "team_id": team_id, "offset": offset, "limit": limit},
    )

    return [str(row[0]) for row in results]


class TestCohort(ClickhouseTestMixin, BaseTest):
    def calculate_cohort_hogql_test_harness(self, cohort: Cohort, pending_version: int):
        from unittest.mock import patch

        # First run: with hogql cohort calculation disabled
        version_without_hogql = pending_version * 2 + 2

        with patch("posthoganalytics.feature_enabled", return_value=False):
            with self.capture_queries_startswith(("INSERT", "insert")) as queries_without_hogql:
                cohort.calculate_people_ch(version_without_hogql)

            results_without_hogql = self._get_cohortpeople(cohort)

            # Check LIMIT in queries
            for query in queries_without_hogql:
                if "LIMIT" in query:
                    assert all(
                        limit == str(MAX_SELECT_COHORT_CALCULATION_LIMIT) for limit in re.findall(r"LIMIT (\d+)", query)
                    )

        # Second run: with hogql cohort calculation enabled
        version_with_hogql = version_without_hogql + 1

        with patch("posthoganalytics.feature_enabled", return_value=True):
            with self.capture_queries_startswith(("INSERT", "insert")) as queries_with_hogql:
                cohort.calculate_people_ch(version_with_hogql)

            results_with_hogql = self._get_cohortpeople(cohort)

            # Check LIMIT in queries
            for query in queries_with_hogql:
                if "LIMIT" in query:
                    assert all(
                        limit == str(MAX_SELECT_COHORT_CALCULATION_LIMIT) for limit in re.findall(r"LIMIT (\d+)", query)
                    )

        # Assert the sets of person_ids are the same
        self.assertCountEqual(results_without_hogql, results_with_hogql)

        # Return the latest version
        return version_with_hogql

    def _get_cohortpeople(self, cohort: Cohort, *, team_id: Optional[int] = None):
        team_id = team_id or cohort.team_id
        return sync_execute(
            GET_COHORTPEOPLE_BY_COHORT_ID,
            {
                "team_id": team_id,
                "cohort_id": cohort.pk,
                "version": cohort.version,
            },
        )

    def test_prop_cohort_basic(self):
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

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {"key": "$some_prop", "value": "something", "type": "person"},
                        {
                            "key": "$another_prop",
                            "value": "something",
                            "type": "person",
                        },
                    ]
                }
            ],
            name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]})
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(
            final_query,
            {**params, **filter.hogql_context.values, "team_id": self.team.pk},
        )
        self.assertEqual(len(result), 1)

    def test_prop_cohort_basic_action(self):
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

        action = _create_action(team=self.team, name="$pageview")
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_id",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=1),
        )

        _create_event(
            event="$not_pageview",
            team=self.team,
            distinct_id="some_other_id",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=2),
        )

        cohort1 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 3}], name="cohort1")

        filter = Filter(
            data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]},
            team=self.team,
        )
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            person_properties_mode=(
                PersonPropertiesMode.USING_SUBQUERY
                if self.team.person_on_events_mode == PersonsOnEventsMode.DISABLED
                else PersonPropertiesMode.DIRECT_ON_EVENTS
            ),
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(
            final_query,
            {**params, **filter.hogql_context.values, "team_id": self.team.pk},
        )

        self.assertEqual(len(result), 1)

    def test_prop_cohort_basic_event_days(self):
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

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_id",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=0, hours=12),
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_other_id",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=4, hours=12),
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"event_id": "$pageview", "days": 1}],
            name="cohort1",
        )

        filter = Filter(
            data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]},
            team=self.team,
        )
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            person_properties_mode=(
                PersonPropertiesMode.USING_SUBQUERY
                if self.team.person_on_events_mode == PersonsOnEventsMode.DISABLED
                else PersonPropertiesMode.DIRECT_ON_EVENTS
            ),
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(
            final_query,
            {**params, **filter.hogql_context.values, "team_id": self.team.pk},
        )
        self.assertEqual(len(result), 1)

        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[{"event_id": "$pageview", "days": 7}],
            name="cohort2",
        )

        filter = Filter(
            data={"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}]},
            team=self.team,
        )
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            person_properties_mode=(
                PersonPropertiesMode.USING_SUBQUERY
                if self.team.person_on_events_mode == PersonsOnEventsMode.DISABLED
                else PersonPropertiesMode.DIRECT_ON_EVENTS
            ),
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(
            final_query,
            {**params, **filter.hogql_context.values, "team_id": self.team.pk},
        )
        self.assertEqual(len(result), 2)

    def test_prop_cohort_basic_action_days(self):
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

        action = _create_action(team=self.team, name="$pageview")
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_id",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(hours=22),
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_other_id",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=5),
        )

        cohort1 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 1}], name="cohort1")

        filter = Filter(
            data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]},
            team=self.team,
        )
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            person_properties_mode=(
                PersonPropertiesMode.USING_SUBQUERY
                if self.team.person_on_events_mode == PersonsOnEventsMode.DISABLED
                else PersonPropertiesMode.DIRECT_ON_EVENTS
            ),
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(
            final_query,
            {**params, **filter.hogql_context.values, "team_id": self.team.pk},
        )
        self.assertEqual(len(result), 1)

        cohort2 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 7}], name="cohort2")

        filter = Filter(
            data={"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}]},
            team=self.team,
        )
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            person_properties_mode=(
                PersonPropertiesMode.USING_SUBQUERY
                if self.team.person_on_events_mode == PersonsOnEventsMode.DISABLED
                else PersonPropertiesMode.DIRECT_ON_EVENTS
            ),
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(
            final_query,
            {**params, **filter.hogql_context.values, "team_id": self.team.pk},
        )
        self.assertEqual(len(result), 2)

    def test_prop_cohort_multiple_groups(self):
        _create_person(
            distinct_ids=["some_other_id"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )

        _create_person(
            distinct_ids=["some_id"],
            team_id=self.team.pk,
            properties={"$another_prop": "something"},
        )
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

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]},
                {"properties": [{"key": "$another_prop", "value": "something", "type": "person"}]},
            ],
            name="cohort1",
        )

        filter = Filter(
            data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]},
            team=self.team,
        )
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(
            final_query,
            {**params, **filter.hogql_context.values, "team_id": self.team.pk},
        )
        self.assertEqual(len(result), 2)

    def test_prop_cohort_with_negation(self):
        team2 = Organization.objects.bootstrap(None)[2]

        _create_person(
            distinct_ids=["some_other_id"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )

        _create_person(
            distinct_ids=["some_id"],
            team_id=team2.pk,
            properties={"$another_prop": "something"},
        )
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

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "type": "person",
                            "key": "$some_prop",
                            "operator": "is_not",
                            "value": "something",
                        }
                    ]
                }
            ],
            name="cohort1",
        )

        filter = Filter(
            data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]},
            team=self.team,
        )
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        self.assertIn("\nFROM person_distinct_id2\n", final_query)

        result = sync_execute(
            final_query,
            {**params, **filter.hogql_context.values, "team_id": self.team.pk},
        )
        self.assertEqual(len(result), 0)

    def test_cohort_get_person_ids_by_cohort_id(self):
        user1 = _create_person(
            distinct_ids=["user1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_person(
            distinct_ids=["user2"],
            team_id=self.team.pk,
            properties={"$some_prop": "another"},
        )
        user3 = _create_person(
            distinct_ids=["user3"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )

        results = get_person_ids_by_cohort_id(self.team.pk, cohort.id)
        self.assertEqual(len(results), 2)
        self.assertIn(str(user1.uuid), results)
        self.assertIn(str(user3.uuid), results)

    def test_insert_by_distinct_id_or_email(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["1"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["123"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["2"])
        # Team leakage
        team2 = Team.objects.create(organization=self.organization)
        Person.objects.create(team=team2, distinct_ids=["1"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        cohort.insert_users_by_list(["1", "123"])
        cohort = Cohort.objects.get()
        results = get_person_ids_by_cohort_id(self.team.pk, cohort.id)
        self.assertEqual(len(results), 2)
        self.assertEqual(cohort.is_calculating, False)

        # test SQLi
        Person.objects.create(team_id=self.team.pk, distinct_ids=["'); truncate person_static_cohort; --"])
        cohort.insert_users_by_list(["'); truncate person_static_cohort; --", "123"])
        results = sync_execute(
            "select count(1) from person_static_cohort where team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )[0][0]
        self.assertEqual(results, 3)

        #  If we accidentally call calculate_people it shouldn't erase people
        self.calculate_cohort_hogql_test_harness(cohort, 0)
        results = get_person_ids_by_cohort_id(self.team.pk, cohort.id)
        self.assertEqual(len(results), 3)

        # if we add people again, don't increase the number of people in cohort
        cohort.insert_users_by_list(["123"])
        results = get_person_ids_by_cohort_id(self.team.pk, cohort.id)
        self.assertEqual(len(results), 3)

    @snapshot_clickhouse_insert_cohortpeople_queries
    def test_cohortpeople_basic(self):
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {"key": "$some_prop", "value": "something", "type": "person"},
                        {
                            "key": "$another_prop",
                            "value": "something",
                            "type": "person",
                        },
                    ]
                }
            ],
            name="cohort1",
        )

        self.calculate_cohort_hogql_test_harness(cohort1, 0)

        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 2)

    def test_cohortpeople_action_basic(self):
        action = _create_action(team=self.team, name="$pageview")
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(hours=12),
        )

        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="2",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(hours=12),
        )

        cohort1 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 1}], name="cohort1")
        self.calculate_cohort_hogql_test_harness(cohort1, 0)

        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 2)

        cohort2 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 1}], name="cohort2")
        self.calculate_cohort_hogql_test_harness(cohort2, 0)

        results = self._get_cohortpeople(cohort2)
        self.assertEqual(len(results), 2)

    def _setup_actions_with_different_counts(self):
        action = _create_action(team=self.team, name="$pageview")
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=1, hours=12),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=0, hours=12),
        )

        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="2",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=1, hours=12),
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="2",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=0, hours=12),
        )

        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["3"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="3",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=0, hours=12),
        )

        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["4"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["5"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )
        return action

    def test_cohortpeople_action_count(self):
        action = self._setup_actions_with_different_counts()

        # test operators
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"action_id": action.pk, "days": 3, "count": 2, "count_operator": "gte"}],
            name="cohort1",
        )
        self.calculate_cohort_hogql_test_harness(cohort1, 0)

        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 2)

        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[{"action_id": action.pk, "days": 3, "count": 1, "count_operator": "lte"}],
            name="cohort2",
        )
        self.calculate_cohort_hogql_test_harness(cohort2, 0)

        results = self._get_cohortpeople(cohort2)
        self.assertEqual(len(results), 1)

        cohort3 = Cohort.objects.create(
            team=self.team,
            groups=[{"action_id": action.pk, "days": 3, "count": 1, "count_operator": "eq"}],
            name="cohort3",
        )
        self.calculate_cohort_hogql_test_harness(cohort3, 0)

        results = self._get_cohortpeople(cohort3)
        self.assertEqual(len(results), 1)

    def test_cohortpeople_deleted_person(self):
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )
        p2 = Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {"key": "$some_prop", "value": "something", "type": "person"},
                        {
                            "key": "$another_prop",
                            "value": "something",
                            "type": "person",
                        },
                    ]
                }
            ],
            name="cohort1",
        )

        self.calculate_cohort_hogql_test_harness(cohort1, 0)
        p2.delete()
        self.calculate_cohort_hogql_test_harness(cohort1, 0)

    def test_cohortpeople_prop_changed(self):
        with freeze_time((datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")):
            p1 = Person.objects.create(
                team_id=self.team.pk,
                distinct_ids=["1"],
                properties={"$some_prop": "something", "$another_prop": "something"},
            )
            p2 = Person.objects.create(
                team_id=self.team.pk,
                distinct_ids=["2"],
                properties={"$some_prop": "something", "$another_prop": "something"},
            )

            cohort1 = Cohort.objects.create(
                team=self.team,
                groups=[
                    {
                        "properties": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
                            {
                                "key": "$another_prop",
                                "value": "something",
                                "type": "person",
                            },
                        ]
                    }
                ],
                name="cohort1",
            )

        self.calculate_cohort_hogql_test_harness(cohort1, 0)

        with freeze_time((datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")):
            p2.version = 1
            p2.properties = {"$some_prop": "another", "$another_prop": "another"}
            p2.save()

        self.calculate_cohort_hogql_test_harness(cohort1, 1)

        results = self._get_cohortpeople(cohort1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], p1.uuid)

    def test_cohort_change(self):
        p1 = Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )
        p2 = Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"$some_prop": "another", "$another_prop": "another"},
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {"key": "$some_prop", "value": "something", "type": "person"},
                        {
                            "key": "$another_prop",
                            "value": "something",
                            "type": "person",
                        },
                    ]
                }
            ],
            name="cohort1",
        )
        self.calculate_cohort_hogql_test_harness(cohort1, 0)
        results = self._get_cohortpeople(cohort1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], p1.uuid)

        cohort1.groups = [
            {
                "properties": [
                    {"key": "$some_prop", "value": "another", "type": "person"},
                    {"key": "$another_prop", "value": "another", "type": "person"},
                ]
            }
        ]
        cohort1.save()

        self.calculate_cohort_hogql_test_harness(cohort1, 1)

        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], p2.uuid)

    def test_static_cohort_precalculated(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["1"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["123"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["2"])
        # Team leakage
        team2 = Team.objects.create(organization=self.organization)
        Person.objects.create(team=team2, distinct_ids=["1"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, last_calculation=timezone.now())
        cohort.insert_users_by_list(["1", "123"])

        self.calculate_cohort_hogql_test_harness(cohort, 0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            sql, _ = format_filter_query(cohort, 0, HogQLContext(team_id=self.team.pk))
            self.assertQueryMatchesSnapshot(sql)

    def test_cohortpeople_with_valid_other_cohort_filter(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["1"], properties={"foo": "bar"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["2"], properties={"foo": "non"})

        cohort0: Cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "foo", "value": "bar", "type": "person"}]}],
            name="cohort0",
        )
        self.calculate_cohort_hogql_test_harness(cohort0, 0)

        cohort1: Cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort0.id}]}],
            name="cohort1",
        )

        self.calculate_cohort_hogql_test_harness(cohort1, 0)

        res = self._get_cohortpeople(cohort1)
        self.assertEqual(len(res), 1)

    @snapshot_clickhouse_insert_cohortpeople_queries
    def test_cohortpeople_with_not_in_cohort_operator(self):
        _create_person(
            distinct_ids=["1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something1"},
        )
        _create_person(
            distinct_ids=["2"],
            team_id=self.team.pk,
            properties={"$some_prop": "something2"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=10),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="2",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=20),
        )

        flush_persons_and_events()

        cohort0: Cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something1", "type": "person"}]}],
            name="cohort0",
        )
        self.calculate_cohort_hogql_test_harness(cohort0, 0)

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "event_type": "events",
                            "key": "$pageview",
                            "negation": False,
                            "time_interval": "year",
                            "time_value": 2,
                            "type": "behavioral",
                            "value": "performed_event",
                        },
                        {
                            "key": "id",
                            "negation": True,
                            "type": "cohort",
                            "value": cohort0.pk,
                        },
                    ],
                }
            },
            name="cohort1",
        )

        self.calculate_cohort_hogql_test_harness(cohort1, 0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            filter = Filter(
                data={
                    "properties": [
                        {
                            "key": "id",
                            "value": cohort1.pk,
                            "type": "precalculated-cohort",
                        }
                    ]
                },
                team=self.team,
            )
            query, params = parse_prop_grouped_clauses(
                team_id=self.team.pk,
                property_group=filter.property_groups,
                hogql_context=filter.hogql_context,
            )
            final_query = "SELECT uuid, distinct_id FROM events WHERE team_id = %(team_id)s {}".format(query)

            result = sync_execute(
                final_query,
                {**params, **filter.hogql_context.values, "team_id": self.team.pk},
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1], "2")  # distinct_id '2' is the one in cohort

    @snapshot_clickhouse_queries
    def test_cohortpeople_with_not_in_cohort_operator_and_no_precalculation(self):
        _create_person(
            distinct_ids=["1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something1"},
        )
        _create_person(
            distinct_ids=["2"],
            team_id=self.team.pk,
            properties={"$some_prop": "something2"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=10),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="2",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=20),
        )

        flush_persons_and_events()

        cohort0: Cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something1", "type": "person"}]}],
            name="cohort0",
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "event_type": "events",
                            "key": "$pageview",
                            "negation": False,
                            "time_interval": "year",
                            "time_value": 2,
                            "type": "behavioral",
                            "value": "performed_event",
                        },
                        {
                            "key": "id",
                            "negation": True,
                            "type": "cohort",
                            "value": cohort0.pk,
                        },
                    ],
                }
            },
            name="cohort1",
        )

        filter = Filter(
            data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]},
            team=self.team,
        )
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid, distinct_id FROM events WHERE team_id = %(team_id)s {}".format(query)
        self.assertIn("\nFROM person_distinct_id2\n", final_query)

        result = sync_execute(
            final_query,
            {**params, **filter.hogql_context.values, "team_id": self.team.pk},
        )
        self.assertEqual(len(result), 2)  # because we didn't precalculate the cohort, both people are in the cohort
        distinct_ids = [r[1] for r in result]
        self.assertCountEqual(distinct_ids, ["1", "2"])

    @snapshot_clickhouse_insert_cohortpeople_queries
    def test_cohortpeople_with_not_in_cohort_operator_for_behavioural_cohorts(self):
        _create_person(
            distinct_ids=["1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_person(
            distinct_ids=["2"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )

        _create_event(
            event="signup",
            team=self.team,
            distinct_id="1",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=10),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=10),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="2",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(days=20),
        )
        flush_persons_and_events()

        cohort0: Cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "event_type": "events",
                            "key": "signup",
                            "negation": False,
                            "time_interval": "day",
                            "time_value": 15,
                            "type": "behavioral",
                            "value": "performed_event_first_time",
                        },
                    ]
                }
            ],
            name="cohort0",
        )
        self.calculate_cohort_hogql_test_harness(cohort0, 0)

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "event_type": "events",
                            "key": "$pageview",
                            "negation": False,
                            "time_interval": "year",
                            "time_value": 2,
                            "type": "behavioral",
                            "value": "performed_event",
                        },
                        {
                            "key": "id",
                            "negation": True,
                            "type": "cohort",
                            "value": cohort0.pk,
                        },
                    ],
                }
            },
            name="cohort1",
        )

        self.calculate_cohort_hogql_test_harness(cohort1, 0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            filter = Filter(
                data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]},
                team=self.team,
            )
            query, params = parse_prop_grouped_clauses(
                team_id=self.team.pk,
                property_group=filter.property_groups,
                hogql_context=filter.hogql_context,
            )
            final_query = "SELECT uuid, distinct_id FROM events WHERE team_id = %(team_id)s {}".format(query)

            result = sync_execute(
                final_query,
                {**params, **filter.hogql_context.values, "team_id": self.team.pk},
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1], "2")  # distinct_id '2' is the one in cohort

    def test_cohortpeople_with_nonexistent_other_cohort_filter(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["1"], properties={"foo": "bar"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["2"], properties={"foo": "non"})

        cohort1: Cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "id", "type": "cohort", "value": 666}]}],
            name="cohort1",
        )

        self.calculate_cohort_hogql_test_harness(cohort1, 0)

        res = self._get_cohortpeople(cohort1)
        self.assertEqual(len(res), 0)

    def test_clickhouse_empty_query(self):
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "nomatchihope", "type": "person"}]}],
            name="cohort1",
        )

        self.calculate_cohort_hogql_test_harness(cohort2, 0)
        self.assertFalse(Cohort.objects.get().is_calculating)

    def test_query_with_multiple_new_style_cohorts(self):
        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[
                {
                    "event": "$autocapture",
                    "url": "https://posthog.com/feedback/123",
                    "url_matching": "exact",
                }
            ],
        )

        # satiesfies all conditions
        p1 = Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"name": "test", "email": "test@posthog.com"},
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            properties={"$current_url": "https://posthog.com/feedback/123"},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=2),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=1),
        )

        # doesn't satisfy action
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["p2"],
            properties={"name": "test", "email": "test@posthog.com"},
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            properties={"$current_url": "https://posthog.com/feedback/123"},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(weeks=3),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=1),
        )

        # satisfies special condition (not pushed down person property in OR group)
        p3 = Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["p3"],
            properties={"name": "special", "email": "test@posthog.com"},
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            properties={"$current_url": "https://posthog.com/feedback/123"},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=2),
        )

        cohort2 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": action1.pk,
                            "event_type": "actions",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        },
                        {
                            "key": "email",
                            "value": "test@posthog.com",
                            "type": "person",
                        },  # this is pushed down
                    ],
                }
            },
            name="cohort2",
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$pageview",
                                    "event_type": "events",
                                    "time_value": 1,
                                    "time_interval": "day",
                                    "value": "performed_event",
                                    "type": "behavioral",
                                },
                                {
                                    "key": "$pageview",
                                    "event_type": "events",
                                    "time_value": 2,
                                    "time_interval": "week",
                                    "value": "performed_event",
                                    "type": "behavioral",
                                },
                                {
                                    "key": "name",
                                    "value": "special",
                                    "type": "person",
                                },  # this is NOT pushed down
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [{"key": "id", "value": cohort2.pk, "type": "cohort"}],
                        },
                    ],
                }
            },
            name="cohort1",
        )

        self.calculate_cohort_hogql_test_harness(cohort2, 0)
        self.calculate_cohort_hogql_test_harness(cohort1, 0)

        result = self._get_cohortpeople(cohort1)
        self.assertCountEqual([p1.uuid, p3.uuid], [r[0] for r in result])

    def test_update_cohort(self):
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something"},
        )
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"$another_prop": "something"},
        )
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["3"],
            properties={"$another_prop": "something"},
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )

        self.calculate_cohort_hogql_test_harness(cohort1, 0)

        # Should only have p1 in this cohort
        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 1)

        cohort1.groups = [{"properties": [{"key": "$another_prop", "value": "something", "type": "person"}]}]
        cohort1.save()
        self.calculate_cohort_hogql_test_harness(cohort1, 1)

        # Should only have p2, p3 in this cohort
        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 2)

        cohort1.groups = [{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}]
        cohort1.save()
        self.calculate_cohort_hogql_test_harness(cohort1, 2)

        # Should only have p1 again in this cohort
        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 1)

    def test_cohort_versioning(self):
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something"},
        )
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"$another_prop": "something"},
        )
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["3"],
            properties={"$another_prop": "something"},
        )

        # start the cohort at some later version
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )

        version = self.calculate_cohort_hogql_test_harness(cohort1, 5)

        cohort1.pending_version = version
        cohort1.version = version
        cohort1.save()

        # Should have p1 in this cohort even if version is different
        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 1)

    def test_calculate_people_ch_in_multiteam_project(self):
        # Create another team in the same project
        team2 = Team.objects.create(organization=self.organization, project=self.team.project)

        # Create people in team 1
        _person1_team1 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"$some_prop": "else"},
        )
        person2_team1 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"$some_prop": "something"},
        )
        # Create people in team 2 with same property
        person1_team2 = _create_person(
            team_id=team2.pk,
            distinct_ids=["person1_team2"],
            properties={"$some_prop": "something"},
        )
        _person2_team2 = _create_person(
            team_id=team2.pk,
            distinct_ids=["person2_team2"],
            properties={"$some_prop": "else"},
        )
        # Create cohort in team 2 (but same project as team 1)
        shared_cohort = Cohort.objects.create(
            team=team2,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="shared cohort",
        )
        # Calculate cohort
        self.calculate_cohort_hogql_test_harness(shared_cohort, 0)

        # Verify shared_cohort is now calculated for both teams
        results_team1 = self._get_cohortpeople(shared_cohort, team_id=self.team.pk)
        results_team2 = self._get_cohortpeople(shared_cohort, team_id=team2.pk)

        self.assertCountEqual([r[0] for r in results_team1], [person2_team1.uuid])
        self.assertCountEqual([r[0] for r in results_team2], [person1_team2.uuid])

    def test_cohortpeople_action_all_events(self):
        # Create an action that matches all events (no specific event defined)
        action = Action.objects.create(team=self.team, name="all events", steps_json=[{"event": None}])

        # Create two people
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        # Create different types of events for both people
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(hours=12),
        )

        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="2",
            properties={"attr": "some_val"},
            timestamp=datetime.now() - timedelta(hours=12),
        )

        # Create a cohort based on the "all events" action
        cohort = Cohort.objects.create(
            team=self.team, groups=[{"action_id": action.pk, "days": 1}], name="cohort_all_events"
        )
        cohort.calculate_people_ch(pending_version=0)

        # Both people should be in the cohort since they both performed some event
        results = self._get_cohortpeople(cohort)
        self.assertEqual(len(results), 2)

        # Create a person with no events
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["3"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        # Recalculate cohort
        cohort.calculate_people_ch(pending_version=1)

        # Should still only have 2 people since person 3 has no events
        results = self._get_cohortpeople(cohort)
        self.assertEqual(len(results), 2)

    @also_test_with_materialized_columns(person_properties=["organization_id"])
    def test_recalculate_cohort_with_list_of_values(self):
        # Create a specific UUID that we'll use both in the person and cohort filter
        matching_uuid = str(uuid.uuid4())

        # Create a person with the matching organization_id
        matching_person = _create_person(
            distinct_ids=["matching_user"],
            team_id=self.team.pk,
            properties={"organization_id": matching_uuid},
        )

        # Create a cohort with the specific filter structure provided
        cohort = Cohort.objects.create(
            team=self.team,
            name="property list cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "organization_id",
                                    "type": "person",
                                    "value": [
                                        matching_uuid,  # Include our matching UUID
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                    ],
                                    "negation": False,
                                    "operator": "exact",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Capture the SQL insert statements when the cohort is calculated
        with self.capture_queries_startswith(("INSERT INTO cohortpeople", "insert into cohortpeople")) as queries:
            self.calculate_cohort_hogql_test_harness(cohort, 0)

        # Assert at least one query was captured
        self.assertTrue(len(queries) > 0, "No queries were captured during cohort calculation")

        # Check that we don't have an excessive number of replaceRegexpAll and JSONExtractRaw functions
        for query in queries:
            # Count instances of replaceRegexpAll and JSONExtractRaw
            replace_regexp_count = query.lower().count("replaceregexpall")
            json_extract_raw_count = query.lower().count("jsonextractraw")

            # Ensure we don't have 11 or more instances of either function
            self.assertLess(replace_regexp_count, 3, "Too many replaceRegexpAll instances found in query")
            self.assertLess(json_extract_raw_count, 3, "Too many JSONExtractRaw instances found in query")

        # Verify that the person with the matching organization_id is in the cohort
        results = self._get_cohortpeople(cohort)
        self.assertEqual(len(results), 1, "Expected one person to be in the cohort")
        self.assertEqual(
            str(results[0][0]), str(matching_person.uuid), "Expected the matching person to be in the cohort"
        )

    @also_test_with_materialized_columns(person_properties=["organization_id"], is_nullable=["organization_id"])
    def test_recalculate_cohort_empty_string_property(self):
        # Create a person with an empty organization_id
        matching_person = _create_person(
            distinct_ids=["matching_user"],
            team_id=self.team.pk,
            properties={"organization_id": ""},
        )

        # Create a cohort with the specific filter structure provided
        cohort = Cohort.objects.create(
            team=self.team,
            name="property list cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "organization_id",
                                    "type": "person",
                                    "value": [
                                        "",  # Include our matching UUID
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                        str(uuid.uuid4()),
                                    ],
                                    "negation": False,
                                    "operator": "exact",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Capture the SQL insert statements when the cohort is calculated
        with self.capture_queries_startswith(("INSERT INTO cohortpeople", "insert into cohortpeople")) as queries:
            self.calculate_cohort_hogql_test_harness(cohort, 0)

        # Assert at least one query was captured
        self.assertTrue(len(queries) > 0, "No queries were captured during cohort calculation")

        # Check that we don't have an excessive number of replaceRegexpAll and JSONExtractRaw functions
        for query in queries:
            # Count instances of replaceRegexpAll and JSONExtractRaw
            replace_regexp_count = query.lower().count("replaceregexpall")
            json_extract_raw_count = query.lower().count("jsonextractraw")

            # Ensure we don't have 11 or more instances of either function
            self.assertLess(replace_regexp_count, 3, "Too many replaceRegexpAll instances found in query")
            self.assertLess(json_extract_raw_count, 3, "Too many JSONExtractRaw instances found in query")

        # Verify that the person with the matching organization_id is in the cohort
        results = self._get_cohortpeople(cohort)
        self.assertEqual(len(results), 1, "Expected one person to be in the cohort")
        self.assertEqual(
            str(results[0][0]), str(matching_person.uuid), "Expected the matching person to be in the cohort"
        )

    def test_recalculate_cohort_with_missing_filter(self):
        # Create a cohort with the specified OR filter structure
        cohort = Cohort.objects.create(
            team=self.team,
            name="behavioral or filter cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "aim_purchase",
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "negation": False,
                                    "event_type": "events",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        with self.assertRaises(ValidationError):
            self.calculate_cohort_hogql_test_harness(cohort, 0)

    def test_cohort_with_inclusion_and_exclusion_and_nested_negation(self):
        # Create two users with different properties
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["user1"], properties={"email": "exclude1", "in_cohort_1": "yes"}
        )
        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["user2"], properties={"email": "exclude2", "in_cohort_1": "yes"}
        )
        _create_person(
            team_id=self.team.pk, distinct_ids=["user3"], properties={"email": "include", "in_cohort_1": "yes"}
        )
        _create_person(team_id=self.team.pk, distinct_ids=["user4"], properties={"in_cohort_1": "yes"})
        flush_persons_and_events()

        cohort_1 = Cohort.objects.create(
            team=self.team,
            name="cohort_1",
            groups=[{"properties": [{"key": "in_cohort_1", "value": "yes", "type": "person", "operator": "exact"}]}],
        )

        cohort_2 = Cohort.objects.create(
            team=self.team,
            name="cohort_2",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "email", "operator": "is_not", "value": "exclude1", "type": "person"},
                                {"key": "email", "operator": "is_not", "value": "exclude2", "type": "person"},
                            ],
                        },
                        {
                            "type": "OR",
                            "values": [
                                {"key": "id", "value": cohort_1.pk, "type": "cohort"},
                            ],
                        },
                    ],
                }
            },
        )

        # Create third cohort that includes cohort_1 and excludes cohort_2
        cohort_3 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "id", "value": cohort_1.pk, "type": "cohort"},
                        {"key": "id", "value": cohort_2.pk, "type": "cohort", "negation": True},
                    ],
                }
            },
            name="cohort_3",
        )
        self.calculate_cohort_hogql_test_harness(cohort_1, 0)
        self.calculate_cohort_hogql_test_harness(cohort_2, 0)
        self.calculate_cohort_hogql_test_harness(cohort_3, 0)

        results = self._get_cohortpeople(cohort_3)
        self.assertEqual(len(results), 2)
        self.assertCountEqual([x[0] for x in results], [p1.uuid, p2.uuid])
