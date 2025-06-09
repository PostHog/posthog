from django.test import TestCase

from posthog.models.user import User


class TestHogFunction(TestCase):
    def setUp(self):
        super().setUp()
        org, team, user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.team = team
        self.user = user
        self.org = org

    def test_hog_flow_basic(self):
        # todo
        pass
