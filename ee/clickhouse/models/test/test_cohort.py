from datetime import datetime, timedelta
from unittest.mock import patch

from django.utils import timezone
from freezegun import freeze_time

from ee.clickhouse.models.cohort import (
    format_filter_query,
    get_person_ids_by_cohort_id,
    recalculate_cohortpeople,
    recalculate_cohortpeople_with_new_query,
)
from ee.clickhouse.models.person import create_person, create_person_distinct_id
from ee.clickhouse.models.property import parse_prop_grouped_clauses
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.client import sync_execute
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.models.organization import Organization
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.test.base import BaseTest, _create_event


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
        create_person_distinct_id(kwargs["team_id"], id, str(person))
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

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],})
        query, params = parse_prop_grouped_clauses(team_id=self.team.pk, property_group=filter.property_groups)
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

        cohort1 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 3}], name="cohort1",)

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],}, team=self.team)
        query, params = parse_prop_grouped_clauses(team_id=self.team.pk, property_group=filter.property_groups)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
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

        cohort1 = Cohort.objects.create(team=self.team, groups=[{"event_id": "$pageview", "days": 1}], name="cohort1",)

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],}, team=self.team)
        query, params = parse_prop_grouped_clauses(team_id=self.team.pk, property_group=filter.property_groups)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 1)

        cohort2 = Cohort.objects.create(team=self.team, groups=[{"event_id": "$pageview", "days": 7}], name="cohort2",)

        filter = Filter(data={"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}],}, team=self.team)
        query, params = parse_prop_grouped_clauses(team_id=self.team.pk, property_group=filter.property_groups)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
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

        cohort1 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 1}], name="cohort1",)

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],}, team=self.team)
        query, params = parse_prop_grouped_clauses(team_id=self.team.pk, property_group=filter.property_groups)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 1)

        cohort2 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 7}], name="cohort2",)

        filter = Filter(data={"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}],}, team=self.team)
        query, params = parse_prop_grouped_clauses(team_id=self.team.pk, property_group=filter.property_groups)
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
            groups=[
                {"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]},
                {"properties": [{"key": "$another_prop", "value": "something", "type": "person"}]},
            ],
            name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],}, team=self.team)
        query, params = parse_prop_grouped_clauses(team_id=self.team.pk, property_group=filter.property_groups)
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
            team=self.team,
            groups=[
                {"properties": [{"type": "person", "key": "$some_prop", "operator": "is_not", "value": "something"}]}
            ],
            name="cohort1",
        )

        filter = Filter(data={"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}],}, team=self.team)
        query, params = parse_prop_grouped_clauses(team_id=self.team.pk, property_group=filter.property_groups)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        self.assertIn("\nFROM person_distinct_id2\n", final_query)

        result = sync_execute(final_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 0)

    def test_cohort_get_person_ids_by_cohort_id(self):
        user1 = _create_person(distinct_ids=["user1"], team_id=self.team.pk, properties={"$some_prop": "something"})
        user2 = _create_person(distinct_ids=["user2"], team_id=self.team.pk, properties={"$some_prop": "another"})
        user3 = _create_person(distinct_ids=["user3"], team_id=self.team.pk, properties={"$some_prop": "something"})
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )

        results = get_person_ids_by_cohort_id(self.team, cohort.id)
        self.assertEqual(len(results), 2)
        self.assertIn(user1.uuid, results)
        self.assertIn(user3.uuid, results)

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

    def test_cohortpeople_basic(self):
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

        results = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
        )
        self.assertEqual(len(results), 2)

    @patch("time.sleep", return_value=None)
    def test_cohortpeople_basic_paginating(self, mock_sleep):
        for i in range(15):
            Person.objects.create(
                team_id=self.team.pk,
                distinct_ids=[f"{i}"],
                properties={"$some_prop": "something", "$another_prop": "something"},
            )

        cohort1: Cohort = Cohort.objects.create(
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

        cohort1.calculate_people(new_version=cohort1.version, batch_size=2, pg_batch_size=1)

        self.assertEqual(len(cohort1.people.all()), 15)

    def test_cohortpeople_action_basic(self):
        action = _create_action(team=self.team, name="$pageview")
        p1 = Person.objects.create(
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

        p2 = Person.objects.create(
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

        cohort1 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 1}], name="cohort1",)
        cohort1.calculate_people_ch(pending_version=0)

        results = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE cohort_id = %(cohort_id)s", {"cohort_id": cohort1.pk}
        )
        self.assertEqual(len(results), 2)

        cohort2 = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 1}], name="cohort2",)
        cohort2.calculate_people_ch(pending_version=0)

        results = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE cohort_id = %(cohort_id)s", {"cohort_id": cohort2.pk}
        )
        self.assertEqual(len(results), 2)

    def _setup_actions_with_different_counts(self):
        action = _create_action(team=self.team, name="$pageview")
        p1 = Person.objects.create(
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

        p2 = Person.objects.create(
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

        p3 = Person.objects.create(
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

        p4 = Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["4"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )

        p5 = Person.objects.create(
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

        results = sync_execute(
            "SELECT person_id FROM cohortpeople where cohort_id = %(cohort_id)s", {"cohort_id": cohort1.pk}
        )
        self.assertEqual(len(results), 2)

        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[{"action_id": action.pk, "days": 3, "count": 1, "count_operator": "lte"}],
            name="cohort2",
        )
        cohort2.calculate_people_ch(pending_version=0)

        results = sync_execute(
            "SELECT person_id FROM cohortpeople where cohort_id = %(cohort_id)s", {"cohort_id": cohort2.pk}
        )
        self.assertEqual(len(results), 1)

        cohort3 = Cohort.objects.create(
            team=self.team,
            groups=[{"action_id": action.pk, "days": 3, "count": 1, "count_operator": "eq"}],
            name="cohort3",
        )
        cohort3.calculate_people_ch(pending_version=0)

        results = sync_execute(
            "SELECT person_id FROM cohortpeople where cohort_id = %(cohort_id)s", {"cohort_id": cohort3.pk}
        )
        self.assertEqual(len(results), 1)

        cohort4 = Cohort.objects.create(
            team=self.team,
            groups=[{"action_id": action.pk, "days": 3, "count": 0, "count_operator": "eq"}],
            name="cohort4",
        )

        cohort4.calculate_people_ch(pending_version=0)
        results = sync_execute(
            "SELECT person_id FROM cohortpeople where cohort_id = %(cohort_id)s", {"cohort_id": cohort3.pk}
        )
        self.assertEqual(len(results), 1)

    def test_cohortpeople_deleted_person(self):
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
            p2.properties = {"$some_prop": "another", "$another_prop": "another"}
            p2.save()

        cohort1.calculate_people_ch(pending_version=0)

        results = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE team_id = %(team_id)s GROUP BY person_id, team_id, cohort_id HAVING sum(sign) > 0",
            {"team_id": self.team.pk},
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], p1.uuid)

    def test_cohort_change(self):
        p1 = Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )
        p2 = Person.objects.create(
            team_id=self.team.pk, distinct_ids=["2"], properties={"$some_prop": "another", "$another_prop": "another"},
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

        results = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE team_id = %(team_id)s GROUP BY person_id, team_id, cohort_id HAVING sum(sign) > 0",
            {"team_id": self.team.pk},
        )

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

        cohort1.calculate_people_ch(pending_version=0)

        results = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE team_id = %(team_id)s GROUP BY person_id, team_id, cohort_id HAVING sum(sign) > 0",
            {"team_id": self.team.pk},
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], p2.uuid)

    def test_static_cohort_precalculated(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["1"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["123"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["2"])
        # Team leakage
        team2 = Team.objects.create(organization=self.organization)
        Person.objects.create(team=team2, distinct_ids=["1"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, last_calculation=timezone.now(),)
        cohort.insert_users_by_list(["1", "123"])

        cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            sql, _ = format_filter_query(cohort)
            self.assertQueryMatchesSnapshot(sql)

    def test_cohortpeople_with_valid_other_cohort_filter(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["1"], properties={"foo": "bar"},)
        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["2"], properties={"foo": "non"},)

        cohort0: Cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": [{"key": "foo", "value": "bar", "type": "person"}]}], name="cohort0",
        )
        cohort0.calculate_people_ch(pending_version=0)

        cohort1: Cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort0.id}]}],
            name="cohort1",
        )

        cohort1.calculate_people_ch(pending_version=0)

        count_result = sync_execute(
            "SELECT count(person_id) FROM cohortpeople where cohort_id = %(cohort_id)s", {"cohort_id": cohort1.pk}
        )[0][0]
        self.assertEqual(count_result, 1)

    def test_cohortpeople_with_nonexistent_other_cohort_filter(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["1"], properties={"foo": "bar"},)
        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["2"], properties={"foo": "non"},)

        cohort1: Cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": [{"key": "id", "type": "cohort", "value": 666}]}], name="cohort1",
        )

        cohort1.calculate_people_ch(pending_version=0)

        count_result = sync_execute(
            "SELECT count(person_id) FROM cohortpeople where cohort_id = %(cohort_id)s", {"cohort_id": cohort1.pk}
        )[0][0]
        self.assertEqual(count_result, 0)

    def test_cohortpeople_with_cyclic_cohort_filter(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["1"], properties={"foo": "bar"},)
        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["2"], properties={"foo": "non"},)

        cohort1: Cohort = Cohort.objects.create(
            team=self.team, groups=[], name="cohort1",
        )
        cohort1.groups = [{"properties": [{"key": "id", "type": "cohort", "value": cohort1.id}]}]
        cohort1.save()

        self.assertRaises(ValueError, lambda: cohort1.calculate_people_ch(pending_version=0))

    def test_cohortpeople_with_misdirecting_cyclic_cohort_filter(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["1"], properties={"foo": "bar"},)
        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["2"], properties={"foo": "non"},)

        cohort1: Cohort = Cohort.objects.create(
            team=self.team, groups=[], name="cohort1",
        )
        cohort2: Cohort = Cohort.objects.create(
            team=self.team, groups=[], name="cohort2",
        )
        cohort3: Cohort = Cohort.objects.create(
            team=self.team, groups=[], name="cohort3",
        )
        cohort4: Cohort = Cohort.objects.create(
            team=self.team, groups=[], name="cohort4",
        )
        cohort5: Cohort = Cohort.objects.create(
            team=self.team, groups=[], name="cohort5",
        )

        cohort1.groups = [{"properties": [{"key": "id", "type": "cohort", "value": cohort2.id}]}]
        cohort1.save()
        cohort2.groups = [{"properties": [{"key": "id", "type": "cohort", "value": cohort3.id}]}]
        cohort2.save()
        cohort3.groups = [{"properties": [{"key": "id", "type": "cohort", "value": cohort4.id}]}]
        cohort3.save()
        cohort4.groups = [{"properties": [{"key": "id", "type": "cohort", "value": cohort2.id}]}]
        cohort4.save()
        cohort5.groups = [{"properties": [{"key": "id", "type": "cohort", "value": cohort1.id}]}]
        cohort5.save()

        # cohort1 depends on cohort2 which depends on cohort3 which depends on cohort4 which depends on cohort2
        # and cohort5 depends on cohort1

        with self.assertRaises(ValueError):
            cohort5.calculate_people_ch(pending_version=0)

        count_result = sync_execute(
            "SELECT count(person_id) FROM cohortpeople where cohort_id = %(cohort_id)s", {"cohort_id": cohort1.pk}
        )[0][0]
        self.assertEqual(count_result, 0)

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
            event="$autocapture", action=action1, url="https://posthog.com/feedback/123", url_matching=ActionStep.EXACT,
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
        p2 = Person.objects.create(
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
                        {"type": "AND", "values": [{"key": "id", "value": cohort2.pk, "type": "cohort",},],},
                    ],
                },
            },
            name="cohort1",
        )

        cohort1.calculate_people_ch(pending_version=0)

        result = sync_execute(
            "SELECT person_id FROM cohortpeople where cohort_id = %(cohort_id)s", {"cohort_id": cohort1.pk}
        )
        self.assertCountEqual([p1.uuid, p3.uuid], [r[0] for r in result])

    def test_new_and_old_aligned(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["1"], properties={"foo": "bar"},)

        p1.properties = {"foo": "bar"}
        p1.save()

        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "days": None,
                    "count": None,
                    "label": None,
                    "end_date": None,
                    "event_id": None,
                    "action_id": None,
                    "properties": [{"key": "foo", "type": "person", "value": "bar"}],
                    "start_date": None,
                    "count_operator": None,
                }
            ],
            name="cohort1",
        )

        count = recalculate_cohortpeople(cohort2)
        new_count = recalculate_cohortpeople_with_new_query(cohort2)

        self.assertEqual(count, new_count)
