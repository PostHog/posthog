import pytest
from posthog.test.base import APIBaseTest

from django.contrib import auth
from django.test import override_settings

from rest_framework import status

from posthog.models import Organization, User


@override_settings(DEMO=True)
@pytest.mark.ee
class TestDemoSignupAPI(APIBaseTest):
    """Demo environment signup tests - signup and login are unified."""

    @classmethod
    def setUpTestData(cls):
        # Do not set up any test data
        pass

    def test_demo_signup(self, *args):
        assert not User.objects.exists()
        assert not Organization.objects.exists()

        # Password not needed
        response = self.client.post(
            "/api/signup/",
            {
                "email": "charlie@tech-r-us.com",
                "first_name": "Charlie",
                "organization_name": "Tech R Us",
                "role_at_organization": "product",
            },
        )
        user = auth.get_user(self.client)
        master_organization = Organization.objects.filter(id=0).first()
        user_organization = Organization.objects.filter(name="Tech R Us").first()

        assert response.status_code == status.HTTP_201_CREATED
        assert Organization.objects.count() == 2  # Master organization "PostHog" & "Tech R Us"
        assert User.objects.count() == 1
        assert isinstance(user, User)
        assert master_organization is not None
        assert master_organization.name == "PostHog"
        assert user_organization is not None
        assert user.organization == user_organization
        assert user.first_name == "Charlie"
        assert user.email == "charlie@tech-r-us.com"
        assert user.is_active is True
        assert user.is_staff is False

    def test_demo_login(self, *args):
        assert not User.objects.exists()
        assert not Organization.objects.exists()

        User.objects.bootstrap("Tech R Us", "charlie@tech-r-us.com", None, first_name="Charlie")

        # first_name and organization_name aren't used when logging in
        # In demo, the signup endpoint functions as login if the email already exists
        response = self.client.post(
            "/api/signup/",
            {
                "email": "charlie@tech-r-us.com",
                "first_name": "X",
                "organization_name": "Y",
            },
        )

        user = auth.get_user(self.client)
        user_organization = Organization.objects.filter(name="Tech R Us").first()

        # 201 is not fully semantically correct here, but it's not really valuable to modify the viewset to return 200
        assert response.status_code == status.HTTP_201_CREATED
        assert Organization.objects.count() == 1
        assert User.objects.count() == 1
        assert isinstance(user, User)
        assert user_organization is not None
        assert user.organization == user_organization
        assert user.first_name == "Charlie"
        assert user.email == "charlie@tech-r-us.com"
        assert user.is_active is True
        assert user.is_staff is False
        self.tearDown()

    def test_social_signup_give_staff_privileges(self, *args):
        assert not User.objects.exists()
        assert not Organization.objects.exists()

        # Simulate SSO process started
        session = self.client.session
        session.update({"backend": "google-oauth2", "email": "charlie@tech-r-us.com"})
        session.save()

        # Staff sign up for demo securely via Google, which should grant is_staff privileges
        response = self.client.post(
            "/api/social_signup/",
            {
                "first_name": "Charlie",
                "email": "charlie@tech-r-us.com",
                "organization_name": "Tech R Us",
                "role_at_organization": "other",
            },
        )

        user = auth.get_user(self.client)
        master_organization = Organization.objects.filter(id=0).first()
        user_organization = Organization.objects.filter(name="Tech R Us").first()

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == {"continue_url": "/complete/google-oauth2/"}
        assert Organization.objects.count() == 2  # Master organization "PostHog" & "Tech R Us"
        assert User.objects.count() == 1
        assert isinstance(user, User)
        assert master_organization is not None
        assert master_organization.name == "PostHog"
        assert user_organization is not None
        assert user.organization == user_organization
        assert user.first_name == "Charlie"
        assert user.email == "charlie@tech-r-us.com"
        assert user.is_active is True
        assert user.is_staff is True

    def test_social_login_give_staff_privileges(self, *args):
        assert not User.objects.exists()
        assert not Organization.objects.exists()

        User.objects.bootstrap("Tech R Us", "charlie@tech-r-us.com", None, first_name="Charlie")

        assert User.objects.get().is_staff is False

        # Simulate SSO process started
        session = self.client.session
        session.update({"backend": "google-oauth2", "email": "charlie@tech-r-us.com"})
        session.save()

        # Staff log into demo securely via Google, which should grant is_staff privileges
        response = self.client.post(
            "/api/social_signup/",
            {
                "first_name": "X",
                "email": "charlie@tech-r-us.com",
                "organization_name": "Y",
                "role_at_organization": "other",
            },
        )

        user = auth.get_user(self.client)
        user_organization = Organization.objects.filter(name="Tech R Us").first()

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == {"continue_url": "/complete/google-oauth2/"}
        assert Organization.objects.count() == 1
        assert User.objects.count() == 1
        assert isinstance(user, User)
        assert user_organization is not None
        assert user.organization == user_organization
        assert user.first_name == "Charlie"
        assert user.email == "charlie@tech-r-us.com"
        assert user.is_active is True
        assert user.is_staff is True
