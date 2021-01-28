import random

from posthog.models import Action, Event, Person, Team
from posthog.test.base import BaseTest


class TestDemo(BaseTest):
    TESTS_API = True

    def test_create_demo_data(self):
        random.seed(900)

        self.client.get("/demo")
        demo_team = Team.objects.get(name__icontains="demo")
        self.assertEqual(Event.objects.count(), 965)
        self.assertEqual(Person.objects.count(), 160)
        self.assertEqual(Action.objects.count(), 8)

        action_event_counts = [action.events.count() for action in Action.objects.all()]
        self.assertCountEqual(action_event_counts, [11, 141, 0, 0, 40, 100, 74, 88])

        self.assertIn("$pageview", demo_team.event_names)
