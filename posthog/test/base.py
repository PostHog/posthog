from typing import Dict, Optional

from django.test import Client, TestCase, TransactionTestCase
from rest_framework.test import APITestCase, APITransactionTestCase

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership


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

    def permission_denied_response(
        self, message: str = "You do not have permission to perform this action.",
    ) -> Dict[str, Optional[str]]:
        return {
            "type": "authentication_error",
            "code": "permission_denied",
            "detail": message,
            "attr": None,
        }


class TestMixin(ErrorResponsesMixin):
    TESTS_API: bool = False
    TESTS_ORGANIZATION_NAME: str = "Test"
    TESTS_EMAIL: Optional[str] = "user1@posthog.com"
    TESTS_PASSWORD: Optional[str] = "testpassword12345"
    TESTS_API_TOKEN: str = "token123"
    TESTS_FORCE_LOGIN: bool = True
    team: Team

    def _create_user(self, email: str, password: Optional[str] = None, first_name: str = "", **kwargs) -> User:
        return User.objects.create_and_join(self.organization, email, password, first_name, **kwargs)

    def setUp(self):
        if hasattr(super(), "setUp"):
            super().setUp()  # type: ignore
        self.organization: Organization = Organization.objects.create(name=self.TESTS_ORGANIZATION_NAME)
        self.team: Team = Team.objects.create(
            organization=self.organization,
            api_token=self.TESTS_API_TOKEN,
            test_account_filters=[
                {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"}
            ],
        )
        if self.TESTS_EMAIL:
            self.user = self._create_user(self.TESTS_EMAIL, self.TESTS_PASSWORD)
            self.organization_membership = self.user.organization_memberships.get()
        if self.TESTS_API:
            self.client = Client()
            if self.TESTS_FORCE_LOGIN and self.TESTS_EMAIL:
                self.client.force_login(self.user)


class BaseTest(TestMixin, TestCase):
    pass


class TransactionBaseTest(TestMixin, TransactionTestCase):
    pass


class APITestMixin(ErrorResponsesMixin):
    """
    Test API using Django REST Framework test suite.
    """

    CONFIG_ORGANIZATION_NAME: str = "Test Co"
    CONFIG_USER_EMAIL: Optional[str] = "user1@posthog.com"
    CONFIG_PASSWORD: Optional[str] = "testpassword12345"
    CONFIG_API_TOKEN: str = "token123"
    CONFIG_AUTO_LOGIN: bool = True

    def _create_user(self, email: str, password: Optional[str] = None, **kwargs) -> User:
        return User.objects.create_and_join(organization=self.organization, email=email, password=password, **kwargs,)

    def setUp(self):
        super().setUp()  # type: ignore
        self.organization: Organization = Organization.objects.create(
            name=self.CONFIG_ORGANIZATION_NAME, plugins_access_level=Organization.PluginsAccessLevel.ROOT
        )
        self.team: Team = Team.objects.create(
            organization=self.organization,
            api_token=self.CONFIG_API_TOKEN,
            test_account_filters=[
                {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"}
            ],
        )
        if self.CONFIG_USER_EMAIL:
            self.user = self._create_user(
                self.CONFIG_USER_EMAIL, self.CONFIG_PASSWORD, level=OrganizationMembership.Level.OWNER
            )
            self.organization_membership = self.user.organization_memberships.get()
            if self.CONFIG_AUTO_LOGIN:
                self.client.force_login(self.user)  # type: ignore


class APIBaseTest(APITestMixin, APITestCase):
    """
    DEPRECATED in favor of APITransactionBaseTest.
    """

    pass


class APITransactionBaseTest(APITestMixin, APITransactionTestCase):
    """
    Test class using Django REST Framework test suite.
    """

    pass
