from typing import Dict, Optional

from django.test import Client, TestCase, TransactionTestCase
from rest_framework.test import APITestCase

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership


class TestMixin:
    TESTS_API: bool = False
    TESTS_COMPANY_NAME: str = "Test"
    TESTS_EMAIL: Optional[str] = "user1@posthog.com"
    TESTS_PASSWORD: Optional[str] = "testpassword12345"
    TESTS_API_TOKEN: str = "token123"
    TESTS_FORCE_LOGIN: bool = True
    team: Team

    def _create_user(self, email: str, password: Optional[str] = None, first_name: str = "", **kwargs) -> User:
        return User.objects.create_and_join(self.organization, email, password, first_name, **kwargs)

    def setUp(self):
        super().setUp()  # type: ignore
        self.organization: Organization = Organization.objects.create(name=self.TESTS_COMPANY_NAME)
        self.team: Team = Team.objects.create(organization=self.organization, api_token=self.TESTS_API_TOKEN)
        if self.TESTS_EMAIL:
            self.user: User = self._create_user(self.TESTS_EMAIL, self.TESTS_PASSWORD)
            self.organization_membership: OrganizationMembership = self.user.organization_memberships.get()
        if self.TESTS_API:
            self.client = Client()
            if self.TESTS_FORCE_LOGIN and self.TESTS_EMAIL:
                self.client.force_login(self.user)


class ErrorResponsesMixin:
    ERROR_RESPONSE_UNAUTHENTICATED: Dict[str, Optional[str]] = {
        "type": "authentication_error",
        "code": "not_authenticated",
        "detail": "Authentication credentials were not provided.",
        "attr": None,
    }

    ERROR_RESPONSE_NOT_FOUND: Dict[str, Optional[str]] = {
        "type": "invalid_request",
        "code": "not_found",
        "detail": "Not found.",
        "attr": None,
    }


class BaseTest(TestMixin, ErrorResponsesMixin, TestCase):
    pass


class TransactionBaseTest(TestMixin, ErrorResponsesMixin, TransactionTestCase):
    pass


class APIBaseTest(ErrorResponsesMixin, APITestCase):
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
            organization=self.organization,
            email=email,
            password=password,
            level=OrganizationMembership.Level.OWNER,
            **kwargs,
        )

    def setUp(self):
        super().setUp()
        self.organization: Organization = Organization.objects.create(name=self.CONFIG_ORGANIZATION_NAME)
        self.team: Team = Team.objects.create(organization=self.organization, api_token=self.CONFIG_API_TOKEN)
        if self.CONFIG_USER_EMAIL:
            self.user = self._create_user(self.CONFIG_USER_EMAIL, self.CONFIG_PASSWORD)
            self.organization_membership = self.user.organization_memberships.get()
            if self.CONFIG_AUTO_LOGIN:
                self.client.force_login(self.user)
