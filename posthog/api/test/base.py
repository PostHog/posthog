from typing import Dict, Optional

from django.test import Client, TestCase, TransactionTestCase
from rest_framework.test import APITestCase

from posthog.cache import clear_cache
from posthog.models import Organization, Team, User


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
        clear_cache()
        self.organization: Organization = Organization.objects.create(name=self.TESTS_COMPANY_NAME)
        self.team: Team = Team.objects.create(organization=self.organization, api_token=self.TESTS_API_TOKEN)
        if self.TESTS_EMAIL:
            self.user = self._create_user(self.TESTS_EMAIL, self.TESTS_PASSWORD)
        if self.TESTS_API:
            self.client = Client()
            if self.TESTS_FORCE_LOGIN and self.TESTS_EMAIL:
                self.client.force_login(self.user)


class ErrorResponsesMixin:

    ERROR_RESPONSE_UNAUTHENTICATED: Dict = {
        "type": "authentication_error",
        "code": "not_authenticated",
        "detail": "Authentication credentials were not provided.",
        "attr": None,
    }

    ERROR_RESPONSE_NOT_FOUND: Dict = {
        "type": "invalid_request",
        "code": "not_found",
        "detail": "Not found.",
        "attr": None,
    }


class BaseTest(TestMixin, TestCase):
    pass


class TransactionBaseTest(TestMixin, TransactionTestCase, ErrorResponsesMixin):
    pass


class APIBaseTest(APITestCase, ErrorResponsesMixin):
    """
    Test API using Django REST Framework test suite.
    """

    CONFIG_ORGANIZATION_NAME: str = "Test"
    CONFIG_USER_EMAIL: Optional[str] = "user1@posthog.com"
    CONFIG_PASSWORD: Optional[str] = "testpassword12345"
    CONFIG_API_TOKEN: str = "token123"
    CONFIG_AUTO_LOGIN: bool = True

    def _create_user(self, email: str, password: Optional[str] = None, **kwargs) -> User:
        return User.objects.create_and_join(
            organization=self.organization, team=self.team, email=email, password=password, **kwargs,
        )

    def setUp(self):
        super().setUp()
        self.organization: Organization = Organization.objects.create(name=self.CONFIG_ORGANIZATION_NAME)
        self.team: Team = Team.objects.create(organization=self.organization, api_token=self.CONFIG_API_TOKEN)

        if self.CONFIG_USER_EMAIL:
            self.user = self._create_user(self.CONFIG_USER_EMAIL, self.CONFIG_PASSWORD)

            if self.CONFIG_AUTO_LOGIN:
                self.client.force_login(self.user)
