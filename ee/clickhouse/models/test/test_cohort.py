from datetime import datetime, timedelta

from django.utils import timezone
from freezegun import freeze_time

from posthog.client import sync_execute
from posthog.hogql.hogql import HogQLContext
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.models.cohort.sql import GET_COHORTPEOPLE_BY_COHORT_ID
from posthog.models.cohort.util import format_filter_query, get_person_ids_by_cohort_id
from posthog.models.filters import Filter
from posthog.models.organization import Organization
from posthog.models.person import Person
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.models.team import Team
from posthog.models.utils import PersonPropertiesMode
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_insert_cohortpeople_queries,
    snapshot_clickhouse_queries,
)


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


class TestCohort(ClickhouseTestMixin, BaseTest):
    def _get_cohortpeople(self, cohort: Cohort):
        return sync_execute(GET_COHORTPEOPLE_BY_COHORT_ID, {"team_id": self.team.pk, "cohort_id": cohort.pk})

    def test_prop_cohort_basic(self):

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

        _create_person(
            distinct_ids=["some_id"],
            team_id=self.team.pk,
            properties={"$some_prop": "something", "$another_prop": "something"},
        )
        _create_person(distinct_ids=["no_match"], team_id=self.team.pk)
        _create_event(event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"})

        _create_event(event="$pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"})

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {"key": "$some_prop", "value": "something", "type": "person"},
                        {"key": "$another_prop", "value": "something", "type": "person"},
                    ]
                }
            ],
            name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]})
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk, property_group=filter.property_groups, hogql_context=filter.hogql_context
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, **filter.hogql_context.values, "team_id": self.team.pk})
        self.assertEqual(len(result), 1)

    def test_prop_cohort_basic_action(self):

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

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

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}, team=self.team)
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self.team.person_on_events_querying_enabled
            else PersonPropertiesMode.USING_SUBQUERY,
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, **filter.hogql_context.values, "team_id": self.team.pk})

        self.assertEqual(len(result), 1)

    def test_prop_cohort_basic_event_days(self):

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

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

        cohort1 = Cohort.objects.create(team=self.team, groups=[{"event_id": "$pageview", "days": 1}], name="cohort1")

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}, team=self.team)
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self.team.person_on_events_querying_enabled
            else PersonPropertiesMode.USING_SUBQUERY,
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, **filter.hogql_context.values, "team_id": self.team.pk})
        self.assertEqual(len(result), 1)

        cohort2 = Cohort.objects.create(team=self.team, groups=[{"event_id": "$pageview", "days": 7}], name="cohort2")

        filter = Filter(data={"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}]}, team=self.team)
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self.team.person_on_events_querying_enabled
            else PersonPropertiesMode.USING_SUBQUERY,
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, **filter.hogql_context.values, "team_id": self.team.pk})
        self.assertEqual(len(result), 2)

    def test_prop_cohort_basic_action_days(self):

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

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

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}, team=self.team)
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self.team.person_on_events_querying_enabled
            else PersonPropertiesMode.USING_SUBQUERY,
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, **filter.hogql_context.values, "team_id": self.team.pk})
        self.assertEqual(len(result), 1)

        cohort2 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 7}], name="cohort2")

        filter = Filter(data={"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}]}, team=self.team)
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self.team.person_on_events_querying_enabled
            else PersonPropertiesMode.USING_SUBQUERY,
            hogql_context=filter.hogql_context,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, **filter.hogql_context.values, "team_id": self.team.pk})
        self.assertEqual(len(result), 2)

    def test_prop_cohort_multiple_groups(self):

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

        _create_person(distinct_ids=["some_id"], team_id=self.team.pk, properties={"$another_prop": "something"})
        _create_event(event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"})

        _create_event(event="$pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"})

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]},
                {"properties": [{"key": "$another_prop", "value": "something", "type": "person"}]},
            ],
            name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}, team=self.team)
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk, property_group=filter.property_groups, hogql_context=filter.hogql_context
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, **filter.hogql_context.values, "team_id": self.team.pk})
        self.assertEqual(len(result), 2)

    def test_prop_cohort_with_negation(self):
        team2 = Organization.objects.bootstrap(None)[2]

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

        _create_person(distinct_ids=["some_id"], team_id=team2.pk, properties={"$another_prop": "something"})
        _create_event(event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"})

        _create_event(event="$pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"})

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {"properties": [{"type": "person", "key": "$some_prop", "operator": "is_not", "value": "something"}]}
            ],
            name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}, team=self.team)
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk, property_group=filter.property_groups, hogql_context=filter.hogql_context
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        self.assertIn("\nFROM person_distinct_id2\n", final_query)

        result = sync_execute(final_query, {**params, **filter.hogql_context.values, "team_id": self.team.pk})
        self.assertEqual(len(result), 0)

    def test_cohort_get_person_ids_by_cohort_id(self):
        user1 = _create_person(distinct_ids=["user1"], team_id=self.team.pk, properties={"$some_prop": "something"})
        _create_person(distinct_ids=["user2"], team_id=self.team.pk, properties={"$some_prop": "another"})
        user3 = _create_person(distinct_ids=["user3"], team_id=self.team.pk, properties={"$some_prop": "something"})
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )

        results = get_person_ids_by_cohort_id(self.team, cohort.id)
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
        results = get_person_ids_by_cohort_id(self.team, cohort.id)
        self.assertEqual(len(results), 2)
        self.assertEqual(cohort.is_calculating, False)

        # test SQLi
        Person.objects.create(team_id=self.team.pk, distinct_ids=["'); truncate person_static_cohort; --"])
        cohort.insert_users_by_list(["'); truncate person_static_cohort; --", "123"])
        results = sync_execute(
            "select count(1) from person_static_cohort where team_id = %(team_id)s", {"team_id": self.team.pk}
        )[0][0]
        self.assertEqual(results, 3)

        #  If we accidentally call calculate_people it shouldn't erase people
        cohort.calculate_people_ch(pending_version=0)
        results = get_person_ids_by_cohort_id(self.team, cohort.id)
        self.assertEqual(len(results), 3)

        # if we add people again, don't increase the number of people in cohort
        cohort.insert_users_by_list(["123"])
        results = get_person_ids_by_cohort_id(self.team, cohort.id)
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
                        {"key": "$another_prop", "value": "something", "type": "person"},
                    ]
                }
            ],
            name="cohort1",
        )

        cohort1.calculate_people_ch(pending_version=0)

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
        cohort1.calculate_people_ch(pending_version=0)

        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 2)

        cohort2 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 1}], name="cohort2")
        cohort2.calculate_people_ch(pending_version=0)

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
        cohort1.calculate_people_ch(pending_version=0)

        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 2)

        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[{"action_id": action.pk, "days": 3, "count": 1, "count_operator": "lte"}],
            name="cohort2",
        )
        cohort2.calculate_people_ch(pending_version=0)

        results = self._get_cohortpeople(cohort2)
        self.assertEqual(len(results), 1)

        cohort3 = Cohort.objects.create(
            team=self.team,
            groups=[{"action_id": action.pk, "days": 3, "count": 1, "count_operator": "eq"}],
            name="cohort3",
        )
        cohort3.calculate_people_ch(pending_version=0)

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
                        {"key": "$another_prop", "value": "something", "type": "person"},
                    ]
                }
            ],
            name="cohort1",
        )

        cohort1.calculate_people_ch(pending_version=0)
        p2.delete()
        cohort1.calculate_people_ch(pending_version=0)

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
                            {"key": "$some_prop", "value": "something", "type": "person"},
                            {"key": "$another_prop", "value": "something", "type": "person"},
                        ]
                    }
                ],
                name="cohort1",
            )

        cohort1.calculate_people_ch(pending_version=0)

        with freeze_time((datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")):
            p2.delete()
            _create_person(
                uuid=p2.uuid,
                team_id=self.team.pk,
                version=1,
                properties={"$some_prop": "another", "$another_prop": "another"},
            )

        cohort1.calculate_people_ch(pending_version=1)

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
            team_id=self.team.pk, distinct_ids=["2"], properties={"$some_prop": "another", "$another_prop": "another"}
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {"key": "$some_prop", "value": "something", "type": "person"},
                        {"key": "$another_prop", "value": "something", "type": "person"},
                    ]
                }
            ],
            name="cohort1",
        )
        cohort1.calculate_people_ch(pending_version=0)
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

        cohort1.calculate_people_ch(pending_version=1)

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

        cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            sql, _ = format_filter_query(cohort, 0, HogQLContext())
            self.assertQueryMatchesSnapshot(sql)

    def test_cohortpeople_with_valid_other_cohort_filter(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["1"], properties={"foo": "bar"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["2"], properties={"foo": "non"})

        cohort0: Cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": [{"key": "foo", "value": "bar", "type": "person"}]}], name="cohort0"
        )
        cohort0.calculate_people_ch(pending_version=0)

        cohort1: Cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort0.id}]}],
            name="cohort1",
        )

        cohort1.calculate_people_ch(pending_version=0)

        res = self._get_cohortpeople(cohort1)
        self.assertEqual(len(res), 1)

    @snapshot_clickhouse_insert_cohortpeople_queries
    def test_cohortpeople_with_not_in_cohort_operator(self):
        _create_person(distinct_ids=["1"], team_id=self.team.pk, properties={"$some_prop": "something1"})
        _create_person(distinct_ids=["2"], team_id=self.team.pk, properties={"$some_prop": "something2"})

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
        cohort0.calculate_people_ch(pending_version=0)

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

        cohort1.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):

            filter = Filter(
                data={"properties": [{"key": "id", "value": cohort1.pk, "type": "precalculated-cohort"}]},
                team=self.team,
            )
            query, params = parse_prop_grouped_clauses(
                team_id=self.team.pk, property_group=filter.property_groups, hogql_context=filter.hogql_context
            )
            final_query = "SELECT uuid, distinct_id FROM events WHERE team_id = %(team_id)s {}".format(query)

            result = sync_execute(final_query, {**params, **filter.hogql_context.values, "team_id": self.team.pk})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1], "2")  # distinct_id '2' is the one in cohort

    @snapshot_clickhouse_queries
    def test_cohortpeople_with_not_in_cohort_operator_and_no_precalculation(self):
        _create_person(distinct_ids=["1"], team_id=self.team.pk, properties={"$some_prop": "something1"})
        _create_person(distinct_ids=["2"], team_id=self.team.pk, properties={"$some_prop": "something2"})

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

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}, team=self.team)
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk, property_group=filter.property_groups, hogql_context=filter.hogql_context
        )
        final_query = "SELECT uuid, distinct_id FROM events WHERE team_id = %(team_id)s {}".format(query)
        self.assertIn("\nFROM person_distinct_id2\n", final_query)

        result = sync_execute(final_query, {**params, **filter.hogql_context.values, "team_id": self.team.pk})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1], "2")  # distinct_id '2' is the one in cohort

    @snapshot_clickhouse_insert_cohortpeople_queries
    def test_cohortpeople_with_not_in_cohort_operator_for_behavioural_cohorts(self):
        _create_person(distinct_ids=["1"], team_id=self.team.pk, properties={"$some_prop": "something"})
        _create_person(distinct_ids=["2"], team_id=self.team.pk, properties={"$some_prop": "something"})

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
        cohort0.calculate_people_ch(pending_version=0)

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

        cohort1.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):

            filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}, team=self.team)
            query, params = parse_prop_grouped_clauses(
                team_id=self.team.pk, property_group=filter.property_groups, hogql_context=filter.hogql_context
            )
            final_query = "SELECT uuid, distinct_id FROM events WHERE team_id = %(team_id)s {}".format(query)

            result = sync_execute(final_query, {**params, **filter.hogql_context.values, "team_id": self.team.pk})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1], "2")  # distinct_id '2' is the one in cohort

    def test_cohortpeople_with_nonexistent_other_cohort_filter(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["1"], properties={"foo": "bar"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["2"], properties={"foo": "non"})

        cohort1: Cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": [{"key": "id", "type": "cohort", "value": 666}]}], name="cohort1"
        )

        cohort1.calculate_people_ch(pending_version=0)

        res = self._get_cohortpeople(cohort1)
        self.assertEqual(len(res), 0)

    def test_clickhouse_empty_query(self):
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "nomatchihope", "type": "person"}]}],
            name="cohort1",
        )

        cohort2.calculate_people_ch(pending_version=0)
        self.assertFalse(Cohort.objects.get().is_calculating)

    def test_query_with_multiple_new_style_cohorts(self):

        action1 = Action.objects.create(team=self.team, name="action1")
        ActionStep.objects.create(
            event="$autocapture", action=action1, url="https://posthog.com/feedback/123", url_matching=ActionStep.EXACT
        )

        # satiesfies all conditions
        p1 = Person.objects.create(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
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
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
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
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "special", "email": "test@posthog.com"}
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
                        {"key": "email", "value": "test@posthog.com", "type": "person"},  # this is pushed down
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
                                {"key": "name", "value": "special", "type": "person"},  # this is NOT pushed down
                            ],
                        },
                        {"type": "AND", "values": [{"key": "id", "value": cohort2.pk, "type": "cohort"}]},
                    ],
                }
            },
            name="cohort1",
        )

        cohort1.calculate_people_ch(pending_version=0)

        result = self._get_cohortpeople(cohort1)
        self.assertCountEqual([p1.uuid, p3.uuid], [r[0] for r in result])

    def test_update_cohort(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["1"], properties={"$some_prop": "something"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["2"], properties={"$another_prop": "something"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["3"], properties={"$another_prop": "something"})

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )

        cohort1.calculate_people_ch(pending_version=0)

        # Should only have p1 in this cohort
        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 1)

        cohort1.groups = [{"properties": [{"key": "$another_prop", "value": "something", "type": "person"}]}]
        cohort1.save()
        cohort1.calculate_people_ch(pending_version=1)

        # Should only have p2, p3 in this cohort
        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 2)

        cohort1.groups = [{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}]
        cohort1.save()
        cohort1.calculate_people_ch(pending_version=2)

        # Should only have p1 again in this cohort
        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 1)

    def test_cohort_versioning(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["1"], properties={"$some_prop": "something"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["2"], properties={"$another_prop": "something"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["3"], properties={"$another_prop": "something"})

        # start the cohort at some later version
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )

        cohort1.calculate_people_ch(pending_version=0)

        cohort1.pending_version = 5
        cohort1.version = 5
        cohort1.save()

        # Should have p1 in this cohort even if version is different
        results = self._get_cohortpeople(cohort1)
        self.assertEqual(len(results), 1)
