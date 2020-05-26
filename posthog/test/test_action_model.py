from posthog.api.test.base import BaseTest
from posthog.models import Person, Event, Action, ActionStep

class TestActions(BaseTest):
    def test_save_with_person_property(self):
        Person.objects.create(team=self.team, distinct_ids=['person1'], properties={'$browser': 'Chrome'})
        Event.objects.create(event='$pageview', distinct_id='person1', team=self.team)
        action = Action.objects.create(name='pageview', team=self.team)
        ActionStep.objects.create(action=action, event='$pageview', properties=[{'key': '$browser', 'value': 'Chrome', 'type': 'person'}])
        action.calculate_events()
        self.assertEqual(action.events.count(), 1)

