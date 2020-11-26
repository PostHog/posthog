from django.test import Client, TestCase

from posthog.models import Action, DashboardItem, Event, Funnel, Person, Team, User
from posthog.test.base import BaseTest


class TestDemo(BaseTest):
    TESTS_API = True

    def test_create_demo_data(self):
        self.client.get("/demo")
        demo_team = Team.objects.get(name__icontains="demo")
        self.assertEqual(Event.objects.count(), 192)
        self.assertEqual(Person.objects.count(), 100)
        self.assertEqual(Action.objects.count(), 4)

        action_event_counts = [action.events.count() for action in Action.objects.all()]
        self.assertCountEqual(action_event_counts, [2, 9, 100, 145])

        self.assertIn("$pageview", demo_team.event_names)
