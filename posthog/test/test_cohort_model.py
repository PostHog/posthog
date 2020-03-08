from posthog.models import Event, Element, Action, ActionStep, Person, Team, Cohort
from posthog.api.test.base import BaseTest

class TestCohort(BaseTest):
    def test_get_distinct_ids_from_cohort(self):
        Person.objects.create(distinct_ids=['person_1'], team=self.team)
        event1 = Event.objects.create(event='user signed up', team=self.team, distinct_id='person_1')
        action = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action, event='user signed up')


        Person.objects.create(distinct_ids=['person_2'], team=self.team, properties={'$os': 'Chrome'})

        cohort = Cohort.objects.create(team=self.team, groups=[{'action_id': action.pk}])
        self.assertEqual(cohort.distinct_ids, ['person_1'])

        cohort = Cohort.objects.create(team=self.team, groups=[{'properties': {'$os': 'Chrome'}}])
        self.assertEqual(cohort.distinct_ids, ['person_2'])

        cohort = Cohort.objects.create(team=self.team, groups=[{'properties': {'$os__icontains': 'Chr'}}])
        self.assertEqual(cohort.distinct_ids, ['person_2'])

        cohort = Cohort.objects.create(team=self.team, groups=[{'action_id': action.pk}, {'properties': {'$os': 'Chrome'}}])
        self.assertCountEqual(cohort.distinct_ids, ['person_1', 'person_2'])