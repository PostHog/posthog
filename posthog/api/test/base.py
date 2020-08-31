from django.test import Client, TestCase, TransactionTestCase
from rest_framework.test import APITestCase

from posthog.models import Team, User


class TestMixin:
    TESTS_API: bool = False
    TESTS_PASSWORD: str = "testpassword12345"
    TESTS_FORCE_LOGIN: bool = True

    def _create_user(self, email, **kwargs) -> User:
        user = User.objects.create_user(email, **kwargs)
        self.team.users.add(user)
        self.team.save()
        return user

    def setUp(self):
        super().setUp()  # type: ignore
        self.team: Team = Team.objects.create(api_token="token123")
        if self.TESTS_API:
            self.client = Client()
            self.user = self._create_user("user1", password=self.TESTS_PASSWORD)
            if self.TESTS_FORCE_LOGIN:
                self.client.force_login(self.user)


class BaseTest(TestMixin, TestCase):
    pass


class TransactionBaseTest(TestMixin, TransactionTestCase):
    pass


class APIBaseTest(APITestCase):
    """
    Test API using Django REST Framework test suite.
    """

    pass
