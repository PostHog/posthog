from typing import Dict, Optional

from django.test import TestCase
from rest_framework.test import APITestCase as DRFTestCase

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership


def _setup_test_data(klass):
    klass.organization = Organization.objects.create(name=klass.CONFIG_ORGANIZATION_NAME)
    klass.team = Team.objects.create(
        organization=klass.organization,
        api_token=klass.CONFIG_API_TOKEN,
        test_account_filters=[
            {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
        ],
    )
    if klass.CONFIG_EMAIL:
        klass.user = User.objects.create_and_join(klass.organization, klass.CONFIG_EMAIL, klass.CONFIG_PASSWORD)
        klass.organization_membership = klass.user.organization_memberships.get()


class ErrorResponsesMixin:
    ERROR_RESPONSE_UNAUTHENTICATED: Dict[str, Optional[str]] = {
        "type": "authentication_error",
        "code": "not_authenticated",
        "detail": "Authentication credentials were not provided.",
        "attr": None,
    }

    ERROR_INVALID_CREDENTIALS = {
        "type": "validation_error",
        "code": "invalid_credentials",
        "detail": "Invalid email or password.",
        "attr": None,
    }

    def not_found_response(self, message: str = "Not found.") -> Dict[str, Optional[str]]:
        return {
            "type": "invalid_request",
            "code": "not_found",
            "detail": message,
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

    def method_not_allowed_response(self, method: str) -> Dict[str, Optional[str]]:
        return {
            "type": "invalid_request",
            "code": "method_not_allowed",
            "detail": f'Method "{method}" not allowed.',
            "attr": None,
        }


class TestMixin:
    CONFIG_ORGANIZATION_NAME: str = "Test"
    CONFIG_EMAIL: Optional[str] = "user1@posthog.com"
    CONFIG_PASSWORD: Optional[str] = "testpassword12345"
    CONFIG_API_TOKEN: str = "token123"
    CONFIG_AUTO_LOGIN: bool = True
    # Most test cases can run with class data level setup. This means that test data gets set up once per class,
    # which can greatly speed up tests. Some tests will require test data to be set up on every test case, setting this
    # to `False` will set up test data on every test case instead.
    CLASS_DATA_LEVEL_SETUP = True

    # Test data definition stubs
    organization: Organization = None  # type: ignore
    team: Team = None  # type: ignore
    user: User = None  # type: ignore
    organization_membership: OrganizationMembership = None  # type: ignore

    def _create_user(self, email: str, password: Optional[str] = None, first_name: str = "", **kwargs) -> User:
        return User.objects.create_and_join(self.organization, email, password, first_name, **kwargs)

    @classmethod
    def setUpTestData(cls):
        if cls.CLASS_DATA_LEVEL_SETUP:
            _setup_test_data(cls)

    def setUp(self):
        if not self.CLASS_DATA_LEVEL_SETUP:
            _setup_test_data(self)


class BaseTest(TestMixin, ErrorResponsesMixin, TestCase):
    """
    Base class for performing Postgres-based backend unit tests on.
    Each class and each test is wrapped inside an atomic block to rollback DB commits after each test.
    Read more: https://docs.djangoproject.com/en/3.1/topics/testing/tools/#testcase 
    """

    pass


class APIBaseTest(TestMixin, ErrorResponsesMixin, DRFTestCase):
    """
    Functional API tests using Django REST Framework test suite.
    """

    def setUp(self):
        super().setUp()
        if self.CONFIG_AUTO_LOGIN and self.user:
            self.client.force_login(self.user)
