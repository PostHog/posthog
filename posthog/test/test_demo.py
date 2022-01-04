import random

from posthog.models import Action, Dashboard, Event, EventDefinition, Person, SessionRecordingEvent, Team
from posthog.test.base import APIBaseTest


class TestDemo(APIBaseTest):
    def test_create_demo_data(self):
        # TODO: test HogflixDataGenerator
        pass
