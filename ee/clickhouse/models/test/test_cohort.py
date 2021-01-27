from datetime import datetime
from uuid import uuid4

from freezegun import freeze_time

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.cohort import format_filter_query, get_person_ids_by_cohort_id
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import create_person, create_person_distinct_id
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.models.event import Event
from posthog.models.filters import Filter
from posthog.models.organization import Organization
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.test.base import BaseTest


def _create_event(**kwargs) -> Event:
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)
    return Event(pk=str(pk))


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


# Some custom stuff for this test as going via Person postgres model won't allow 2 people with same ID
def _create_person(**kwargs) -> Person:
    if kwargs.get("uuid"):
        uuid = str(kwargs.pop("uuid"))
    else:
        uuid = str(UUIDT())
    distinct_ids = kwargs.pop("distinct_ids")
    person = create_person(uuid=uuid, **kwargs)
    for id in distinct_ids:
        create_person_distinct_id(0, kwargs["team_id"], id, str(person))
    return Person(id=person, uuid=person)


class TestCohort(ClickhouseTestMixin, BaseTest):
    def test_prop_cohort_basic(self):

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

        _create_person(
            distinct_ids=["some_id"],
            team_id=self.team.pk,
            properties={"$some_prop": "something", "$another_prop": "something"},
        )
        _create_person(distinct_ids=["no_match"], team_id=self.team.pk)
        _create_event(
            event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"},
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": {"$some_prop": "something", "$another_prop": "something"}}],
            name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],})
        query, params = parse_prop_clauses(filter.properties, self.team.pk)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
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
            event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"},
        )

        _create_event(
            event="$not_pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"},
        )

        cohort1 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk}], name="cohort1",)

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],})
        query, params = parse_prop_clauses(filter.properties, self.team.pk)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 1)

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
            timestamp=datetime(2020, 1, 9, 12, 0, 1),
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_other_id",
            properties={"attr": "some_val"},
            timestamp=datetime(2020, 1, 5, 12, 0, 1),
        )

        with freeze_time("2020-01-10"):
            cohort1 = Cohort.objects.create(
                team=self.team, groups=[{"action_id": action.pk, "days": 1}], name="cohort1",
            )

            filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],})
            query, params = parse_prop_clauses(filter.properties, self.team.pk)
            final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
            result = sync_execute(final_query, {**params, "team_id": self.team.pk})
            self.assertEqual(len(result), 1)

            cohort2 = Cohort.objects.create(
                team=self.team, groups=[{"action_id": action.pk, "days": 7}], name="cohort2",
            )

            filter = Filter(data={"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}],})
            query, params = parse_prop_clauses(filter.properties, self.team.pk)
            final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
            result = sync_execute(final_query, {**params, "team_id": self.team.pk})
            self.assertEqual(len(result), 2)

    def test_prop_cohort_multiple_groups(self):

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

        _create_person(distinct_ids=["some_id"], team_id=self.team.pk, properties={"$another_prop": "something"})
        _create_event(
            event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"},
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": {"$some_prop": "something"}}, {"properties": {"$another_prop": "something"}}],
            name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],})
        query, params = parse_prop_clauses(filter.properties, self.team.pk)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 2)

    def test_prop_cohort_with_negation(self):
        team2 = Organization.objects.bootstrap(None)[2]

        _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})

        _create_person(distinct_ids=["some_id"], team_id=team2.pk, properties={"$another_prop": "something"})
        _create_event(
            event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"},
        )

        cohort1 = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop__is_not": "something"}}], name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],})
        query, params = parse_prop_clauses(filter.properties, self.team.pk)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 0)

    def test_cohort_updated_props(self):
        # The way clickhouse works is that updates aren't instant, so two people with the same ID are in the database
        # Make sure we get the last one.
        person1 = _create_person(
            distinct_ids=["some_other_id_2"],
            team_id=self.team.pk,
            properties={"$some_prop": "updated"},
            timestamp=datetime(2020, 1, 1, 12, 0, 1),
        )
        _create_person(
            uuid=person1.uuid,
            distinct_ids=["some_other_id"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
            timestamp=datetime(2020, 1, 1, 12, 0, 4),
        )

        cohort1 = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "updated"}}], name="cohort1",
        )

        final_query, params = format_filter_query(cohort1)

        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 0)

    def test_cohort_get_person_ids_by_cohort_id(self):
        user1 = _create_person(distinct_ids=["user1"], team_id=self.team.pk, properties={"$some_prop": "something"})
        user2 = _create_person(distinct_ids=["user2"], team_id=self.team.pk, properties={"$some_prop": "another"})
        user3 = _create_person(distinct_ids=["user3"], team_id=self.team.pk, properties={"$some_prop": "something"})
        cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "something"}}], name="cohort1",
        )

        results = get_person_ids_by_cohort_id(self.team, cohort.id)
        self.assertEqual(len(results), 2)
        self.assertIn(user1.uuid, results)
        self.assertIn(user3.uuid, results)

    def test_insert_by_distinct_id_or_email(self):
        Person.objects.create(team_id=self.team.pk, properties={"email": "email@example.org"}, distinct_ids=["1"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["123"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["2"])
        # Team leakage
        team2 = Team.objects.create(organization=self.organization)
        Person.objects.create(team=team2, properties={"email": "email@example.org"})

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        cohort.insert_users_by_list(["email@example.org", "123"])
        cohort = Cohort.objects.get()
        results = get_person_ids_by_cohort_id(self.team, cohort.id)
        self.assertEqual(len(results), 2)
        self.assertEqual(cohort.is_calculating, False)

        # test SQLi
        Person.objects.create(team_id=self.team.pk, distinct_ids=["'); truncate person_static_cohort; --"])
        cohort.insert_users_by_list(["'); truncate person_static_cohort; --", "123"])
        results = sync_execute("select count(1) from person_static_cohort")[0][0]
        self.assertEqual(results, 3)

        #  If we accidentally call calculate_people it shouldn't erase people
        cohort.calculate_people()
        results = get_person_ids_by_cohort_id(self.team, cohort.id)
        self.assertEqual(len(results), 3)

        # if we add people again, don't increase the number of people in cohort
        cohort.insert_users_by_list(["123"])
        results = get_person_ids_by_cohort_id(self.team, cohort.id)
        self.assertEqual(len(results), 3)
