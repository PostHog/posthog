from posthog.models import Action, Event, Person, Team
from posthog.test.base import BaseTest


class TestDemo(BaseTest):
    TESTS_API = True

    def test_create_demo_data(self):
        self.client.get("/demo")
        demo_team = Team.objects.get(name__icontains="demo")
        self.assertGreater(Event.objects.count(), 10000)
        self.assertGreater(Person.objects.count(), 100)
        self.assertGreater(Action.objects.count(), 5)
        self.assertIn("$pageview", demo_team.event_names)
