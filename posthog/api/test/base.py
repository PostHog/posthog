from django.test import TestCase
from posthog.models import User, Team
from django.test import Client


class BaseTest(TestCase):
    TESTS_API: bool = False
    def _create_user(self, email, **kwargs) -> User:
        user = User.objects.create_user(email, **kwargs)
        if not hasattr(self, 'team'):
            self.team: Team = Team.objects.create(api_token='token123')
        self.team.users.add(user)
        self.team.save()
        return user

    def setUp(self):
        super().setUp()
        self.team: Team = Team.objects.create(api_token='token123')
        if self.TESTS_API:
            self.client = Client()
            self.user = self._create_user('user1')
            self.client.force_login(self.user)
    