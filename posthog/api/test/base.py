from typing import Optional

from django.test import Client, TestCase, TransactionTestCase
from rest_framework.test import APITestCase

from posthog.models import Organization, OrganizationMembership, Team, User, organization


class TestMixin:
    TESTS_API: bool = False
    TESTS_COMPANY_NAME: str = "Test"
    TESTS_EMAIL: Optional[str] = "user1@posthog.com"
    TESTS_PASSWORD: Optional[str] = "testpassword12345"
    TESTS_API_TOKEN: str = "token123"
    TESTS_FORCE_LOGIN: bool = True

    def _create_user(self, email: str, password: Optional[str] = None, first_name: str = "", **kwargs) -> User:
        return User.objects.create_and_join(self.organization, self.team, email, password, first_name, **kwargs)

    def setUp(self):
        super().setUp()  # type: ignore
        self.organization: Organization = Organization.objects.create(name=self.TESTS_COMPANY_NAME)
        self.team: Team = Team.objects.create(organization=self.organization, api_token=self.TESTS_API_TOKEN)
        if self.TESTS_EMAIL:
            self.user = self._create_user(self.TESTS_EMAIL, self.TESTS_PASSWORD)
        if self.TESTS_API:
            self.client = Client()
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

    TESTS_COMPANY_NAME: str = "Test"
    TESTS_EMAIL: str = "user1@posthog.com"
    TESTS_PASSWORD: Optional[str] = "testpassword12345"
    TESTS_API_TOKEN: str = "token123"
    TESTS_FORCE_LOGIN: bool = True

    def _create_user(self, email: str, password: Optional[str] = None, **kwargs) -> User:
        return User.objects.create_and_join(
            organization=self.organization, team=self.team, email=email, password=password, **kwargs
        )

    def setUp(self):
        super().setUp()
        self.organization: Organization = Organization.objects.create(name=self.TESTS_COMPANY_NAME)
        self.team: Team = Team.objects.create(organization=self.organization, api_token=self.TESTS_API_TOKEN)
        self.user = self._create_user(self.TESTS_EMAIL, self.TESTS_PASSWORD)
        if self.TESTS_FORCE_LOGIN:
            self.client.force_login(self.user)
