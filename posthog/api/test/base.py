from django.test import Client, TestCase, TransactionTestCase
from rest_framework.test import APITestCase

from posthog.models import Team, User
from posthog.models.organization import Organization, OrganizationMembership


class TestMixin:
    TESTS_API: bool = False
    TESTS_PASSWORD: str = "testpassword12345"
    TESTS_FORCE_LOGIN: bool = True

    def _create_user(self, email, **kwargs) -> User:
        user = User.objects.create_user(email, current_team=self.team, **kwargs)
        self.team.users.add(user)
        self.team.save()
        return user

    def setUp(self):
        super().setUp()  # type: ignore
        self.organization: Organization = Organization.objects.create(name="Test Org")
        self.team: Team = Team.objects.create(organization=self.organization, name="Test", api_token="token123")
        if self.TESTS_API:
            self.client = Client()
            self.user = self._create_user("user1", password=self.TESTS_PASSWORD)
            self.organization_membership_admin = OrganizationMembership.objects.create(
                user=self.user, organization=self.organization, level=OrganizationMembership.Level.ADMIN
            )
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
