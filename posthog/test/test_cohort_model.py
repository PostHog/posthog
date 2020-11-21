from unittest.mock import patch

from django.test import tag
from freezegun import freeze_time

from posthog.api.test.base import BaseTest
from posthog.models import Action, ActionStep, Cohort, Element, Event, Person, Team


class TestCohort(BaseTest):
    def test_postgres_get_distinct_ids_from_cohort(self):
        person1 = Person.objects.create(distinct_ids=["person_1"], team=self.team)
        event1 = Event.objects.create(event="user signed up", team=self.team, distinct_id="person_1")
        action = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action, event="user signed up")
        action.calculate_events()

        person2 = Person.objects.create(distinct_ids=["person_2"], team=self.team, properties={"$os": "Chrome"})
        person3 = Person.objects.create(distinct_ids=["person_3"], team=self.team)
        person4 = Person.objects.create(distinct_ids=["person_4"], team=self.team)

        cohort = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 7}])
        cohort.calculate_people(use_clickhouse=False)
        with self.assertNumQueries(1):
            self.assertEqual([p for p in cohort.people.all()], [person1])

        cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        cohort.calculate_people(use_clickhouse=False)
        self.assertEqual([p for p in cohort.people.all()], [person2])

        cohort = Cohort.objects.create(team=self.team, groups=[{"properties": {"$os__icontains": "Chr"}}])
        cohort.calculate_people(use_clickhouse=False)
        self.assertEqual([p for p in cohort.people.all()], [person2])

        cohort = Cohort.objects.create(
            team=self.team, groups=[{"action_id": action.pk}, {"properties": {"$os": "Chrome"}}],
        )
        cohort.calculate_people(use_clickhouse=False)
        self.assertCountEqual([p for p in cohort.people.all()], [person1, person2])

    @tag("ee")
    @patch("ee.clickhouse.models.cohort.get_person_ids_by_cohort_id")
    def test_calculating_cohort_clickhouse(self, get_person_ids_by_cohort_id):
        person1 = Person.objects.create(
            distinct_ids=["person1"], team_id=self.team.pk, properties={"$some_prop": "something"}
        )
        person2 = Person.objects.create(distinct_ids=["person2"], team_id=self.team.pk, properties={})
        person3 = Person.objects.create(
            distinct_ids=["person3"], team_id=self.team.pk, properties={"$some_prop": "something"}
        )
        cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "something"}}], name="cohort1",
        )

        get_person_ids_by_cohort_id.return_value = [person1.uuid, person2.uuid]

        cohort.calculate_people(use_clickhouse=True)

        self.assertCountEqual(list(cohort.people.all()), [person1, person2])

    @tag("ee")
    def test_clickhouse_empty_query(self):
        cohort2 = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "nomatchihope"}}], name="cohort1",
        )

        cohort2.calculate_people(use_clickhouse=True)
        self.assertFalse(Cohort.objects.get().is_calculating)

    def test_empty_query(self):
        cohort2 = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "nomatchihope"}}], name="cohort1",
        )

        cohort2.calculate_people()
        self.assertFalse(Cohort.objects.get().is_calculating)
