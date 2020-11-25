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
        self.assertEqual(Action.objects.all()[1].events.count(), 9)
        self.assertIn("$pageview", demo_team.event_names)
