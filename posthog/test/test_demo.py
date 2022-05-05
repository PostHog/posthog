import random

from posthog.client import sync_execute
from posthog.models import Action, Dashboard, EventDefinition, Team
from posthog.test.base import APIBaseTest


class TestDemo(APIBaseTest):
    def test_create_demo_data(self):
        random.seed(900)

        self.client.get("/demo")
        demo_team = Team.objects.get(name__icontains="demo")
        self.assertEqual(demo_team.is_demo, True)
        self.assertEqual(Dashboard.objects.count(), 3)
        self.assertGreaterEqual(len(sync_execute("SELECT * FROM events")), 900)
        self.assertGreaterEqual(len(sync_execute("SELECT * FROM person")), 160)
        self.assertGreaterEqual(Action.objects.count(), 8)
        self.assertGreaterEqual(len(sync_execute("SELECT * FROM session_recording_events")), 60)

        # TODO: We need a better way to test this, inconsistent results locally and on CI
        # action_event_counts = [action.events.count() for action in Action.objects.all()]
        # self.assertCountEqual(action_event_counts, [14, 140, 0, 0, 40, 100, 73, 87])

        self.assertTrue(EventDefinition.objects.filter(team=demo_team, name="$pageview").exists())
