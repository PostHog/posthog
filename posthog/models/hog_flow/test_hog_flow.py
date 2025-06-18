from django.test import TestCase

from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.models.team import Team
from posthog.models.user import User


class TestHogFlow(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Test Team")
        self.user = User.objects.create_user(username="test@posthog.com", password="test")
        self.hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Test Flow",
            status=HogFlow.State.ACTIVE,
            trigger={"type": "event", "filters": []},
            edges=[],
            actions=[],
        )

    def test_stop_type_choices(self):
        """Test that stop_type can only be set to valid choices"""
        self.hog_flow.stop_type = HogFlow.StopType.TRIGGER
        self.hog_flow.save()
        self.assertEqual(self.hog_flow.stop_type, HogFlow.StopType.TRIGGER)

        self.hog_flow.stop_type = HogFlow.StopType.ALL
        self.hog_flow.save()
        self.assertEqual(self.hog_flow.stop_type, HogFlow.StopType.ALL)

        # Test invalid choice
        with self.assertRaises(Exception):
            self.hog_flow.stop_type = "invalid"
            self.hog_flow.save()

    def test_archive_with_stop_type(self):
        """Test that a flow can be archived with a stop_type"""
        self.hog_flow.status = HogFlow.State.ARCHIVED
        self.hog_flow.stop_type = HogFlow.StopType.TRIGGER
        self.hog_flow.save()

        saved_flow = HogFlow.objects.get(id=self.hog_flow.id)
        self.assertEqual(saved_flow.status, HogFlow.State.ARCHIVED)
        self.assertEqual(saved_flow.stop_type, HogFlow.StopType.TRIGGER)

    def test_version_conflict_detection(self):
        """Test that saving a flow with an outdated version raises a validation error"""
        # Create initial flow
        flow = HogFlow.objects.create(
            team=self.team,
            name="Test Flow",
            status=HogFlow.State.ACTIVE,
            trigger={"type": "event", "filters": []},
            edges=[],
            actions=[],
        )

        # Simulate concurrent edit by directly updating the version
        flow.version = 2
        flow.save()

        # Try to save with old version
        flow.version = 1
        with self.assertRaises(Exception) as context:
            flow.save()

        self.assertIn("version", str(context.exception))
