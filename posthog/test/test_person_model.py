from posthog.api.test.base import BaseTest
from posthog.models import Action, ActionStep, Cohort, Element, Event, Person, Team


class TestPerson(BaseTest):
    def test_merge_people(self):
        person0 = Person.objects.create(distinct_ids=["person_0"], team=self.team, properties={"$os": "Microsoft"})

        person1 = Person.objects.create(distinct_ids=["person_1"], team=self.team, properties={"$os": "Chrome"})
        event1 = Event.objects.create(event="user signed up", team=self.team, distinct_id="person_1")
        action = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action, event="user signed up")
        action.calculate_events()

        person2 = Person.objects.create(
            distinct_ids=["person_2"], team=self.team, properties={"$os": "Apple", "$browser": "MS Edge"}
        )
        person3 = Person.objects.create(distinct_ids=["person_3"], team=self.team, properties={"$os": "PlayStation"})

        cohort = Cohort.objects.create(team=self.team, groups=[{"action_id": action.pk, "days": 7}])
        cohort.calculate_people()
        self.assertEqual([p for p in cohort.people.all()], [person1])

        self.assertEqual(len(Person.objects.all()), 4)

        person0.merge_people([person1, person2, person3])

        self.assertEqual(len(Person.objects.all()), 1)

        person0 = Person.objects.get(pk=person0.pk)
        self.assertEqual(person0.properties, {"$os": "Microsoft", "$browser": "MS Edge"})
        self.assertEqual(person0.distinct_ids, ["person_0", "person_1", "person_2", "person_3"])
        self.assertEqual([p for p in cohort.people.all()], [person0])
