from posthog.models import Event, Element, Action, ActionStep, Person, Team, Cohort
from posthog.api.test.base import BaseTest


class TestCohort(BaseTest):
    def test_get_distinct_ids_from_cohort(self):
        person1 = Person.objects.create(distinct_ids=["person_1"], team=self.team)
        event1 = Event.objects.create(event="user signed up", team=self.team, distinct_id="person_1")
        action = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action, event="user signed up")
        action.calculate_events()

        person2 = Person.objects.create(distinct_ids=["person_2"], team=self.team, properties={"$os": "Chrome"})
        person3 = Person.objects.create(distinct_ids=["person_3"], team=self.team)
        person4 = Person.objects.create(distinct_ids=["person_4"], team=self.team)

        cohort = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 7}])
        cohort.calculate_people()
        with self.assertNumQueries(1):
            self.assertEqual([p for p in cohort.people.all()], [person1])

        cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        cohort.calculate_people()
        self.assertEqual([p for p in cohort.people.all()], [person2])

        cohort = Cohort.objects.create(team=self.team, groups=[{"properties": {"$os__icontains": "Chr"}}])
        cohort.calculate_people()
        self.assertEqual([p for p in cohort.people.all()], [person2])

        cohort = Cohort.objects.create(
            team=self.team, groups=[{"action_id": action.pk}, {"properties": {"$os": "Chrome"}}],
        )
        cohort.calculate_people()
        self.assertCountEqual([p for p in cohort.people.all()], [person1, person2])
