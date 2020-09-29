import random
from typing import Dict, List, Tuple
from unittest.mock import patch

from django.db.models import Q
from django.test import tag
from rest_framework import status

from posthog.models import Organization, Team, User

from .base import APIBaseTest


class TestTeamUser(APIBaseTest):
    def create_user_for_team_org(self, team: Team, organization: Organization) -> User:
        suffix = random.randint(100000, 999999)
        user = User.objects.create_and_join(
            organization, team, f"user{suffix}@posthog.com", self.TESTS_PASSWORD, first_name=f"User #{suffix}",
        )
        return user

    def create_org_team_user(self, api_token: str = "token456") -> Tuple[Organization, Team, User]:
        organization: Organization = Organization.objects.create(name="Test")
        team: Team = Team.objects.create(organization=organization, name="Test", api_token=api_token)
        return (organization, team, self.create_user_for_team_org(team, organization))

    def test_user_can_list_their_teams(self):

        # Create a team with a list of multiple users first
        teams: List = []
        for i in range(1, 4):
            team = Team.objects.create(name=f"Test {i}", api_token=str(i))
            team.users.add(self.user)
            teams.append(team)

        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data: Dict = response.json()

        self.assertEqual(
            set(map(lambda team: team["name"], response_data["teams"])), {"Test", "Test 1", "Test 2", "Test 3"}
        )

    def test_user_can_list_their_team_users(self):

        # Create a team with a list of multiple users first
        users: List = []
        organization, team, user = self.create_org_team_user()
        users.append(user)
        for i in range(0, 3):
            users.append(self.create_user_for_team_org(team, organization))

        self.client.force_login(random.choice(users))  # Log in as any of the users

        response = self.client.get("/api/organization/members/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()

        self.assertEqual(response_data["count"], 4)

        EXPECTED_ATTRS: List = ["id", "distinct_id", "first_name", "email"]
        user_ids: List = [x.distinct_id for x in users]

        for _user in response_data["results"]:
            self.assertEqual(list(_user.keys()), EXPECTED_ATTRS)

            self.assertIn(_user["distinct_id"], user_ids)  # Make sure only the correct users are returned

    def test_user_can_change_current_team(self):
        team1: Team = Team.objects.create(name="Test 111", api_token="token_ein")
        team1.save()
        team2: Team = Team.objects.create(name="Test 222", api_token="token_zwei")
        team2.save()
        team1.users.add(self.user)
        team2.users.add(self.user)
        response = self.client.get("/api/user/", content_type="application/json",)
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data["team"]["name"], "Default")
        self.assertEqual(response_data["team"]["api_token"], "token")

        response = self.client.patch(
            "/api/user/", data={"user": {"current_team_id": team2.id}}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data["team"]["name"], "Test 222")
        self.assertEqual(response_data["team"]["api_token"], "token_zwei")

    def test_user_cannot_switch_to_unavailable_team(self):
        team1: Team = Team.objects.create(name="app1", api_token="token_zwei")

        response = self.client.patch(
            "/api/user/", data={"user": {"current_team_id": team1.id}}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.patch(
            "/api/user/", data={"user": {"current_team_id": 54353453}}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_user_can_only_switch_teams_with_id(self):
        response = self.client.patch(
            "/api/user/", data={"user": {"current_team_id": "abc"}}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_user_can_delete_another_team_user(self):
        organization, team, user = self.create_org_team_user()
        user2: User = self.create_user_for_team_org(team, organization)
        self.client.force_login(user)

    @patch("posthog.api.team.posthoganalytics.capture")
    def test_user_can_delete_another_team_user(self, mock_capture):
        organization, team, user = self.create_org_team_user()
        user2: User = self.create_user_for_team_org(team, organization)
        self.client.force_login(user)

        response = self.client.delete(f"/api/organization/member/{user2.distinct_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(User.objects.get(id=user2.id).is_active)
        self.assertFalse(team.users.filter(Q(pk=user2.pk) | Q(distinct_id=user2.distinct_id)).exists())

        # Assert that the event is reported to PH
        mock_capture.assert_any_call(
            user.distinct_id, "team member deleted", {"deleted_team_member": user2.distinct_id}
        )
        mock_capture.assert_any_call(user2.distinct_id, "this user deleted")

    @patch("posthog.api.team.posthoganalytics.capture")
    def test_cannot_delete_yourself(self, mock_capture):
        organization, team, user = self.create_org_team_user()
        self.client.force_login(user)

        response = self.client.delete(f"/api/organization/member/{user.distinct_id}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"detail": "Cannot delete yourself."})

        self.assertEqual(
            User.objects.filter(Q(pk=user.pk) | Q(distinct_id=user.distinct_id)).count(), 1,
        )  # User still exists

        # Assert no event was repoted to PH
        mock_capture.assert_not_called()

    def test_cannot_delete_user_using_their_primary_key(self):
        organization, team, user = self.create_org_team_user()
        user2: User = self.create_user_for_team_org(team, organization)
        self.client.force_login(user)

        response = self.client.delete(f"/api/organization/member/{user2.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), {"detail": "Not found."})

        self.assertEqual(
            User.objects.filter(Q(pk=user2.pk) | Q(distinct_id=user2.distinct_id)).count(), 1,
        )  # User still exists

    def test_user_cannot_delete_user_from_another_team(self):
        organization, team, user = self.create_org_team_user()
        self.client.force_login(user)

        organization2, team2, user2 = self.create_org_team_user("token789")

        response = self.client.delete(f"/api/organization/member/{user2.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), {"detail": "Not found."})

        self.assertEqual(
            User.objects.filter(Q(pk=user2.pk) | Q(distinct_id=user2.distinct_id)).count(), 1,
        )  # User still exists

    def test_creating_or_updating_users_is_currently_not_allowed(self):
        organization, team, user = self.create_org_team_user()
        self.client.force_login(user)

        # Cannot partially update users
        email: str = user.email
        response = self.client.patch(
            f"/api/organization/member/{user.distinct_id}", {"email": "newemail@posthog.com"}, "json"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            response.json(),
            {
                "type": "invalid_request",
                "code": "method_not_allowed",
                "detail": 'Method "PATCH" not allowed.',
                "attr": None,
            },
        )

        # Cannot update users
        response = self.client.put(
            f"/api/organization/member/{user.distinct_id}/", {"email": "newemail@posthog.com"}, "json"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            response.json(),
            {
                "type": "invalid_request",
                "code": "method_not_allowed",
                "detail": 'Method "PUT" not allowed.',
                "attr": None,
            },
        )

        user.refresh_from_db()
        self.assertEqual(user.email, email)

        # Cannot create users
        count: int = User.objects.count()
        response = self.client.post(
            f"/api/organization/member/{user.distinct_id}/", {"email": "newuser@posthog.com"}, "json"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            response.json(),
            {
                "type": "invalid_request",
                "code": "method_not_allowed",
                "detail": 'Method "POST" not allowed.',
                "attr": None,
            },
        )
        self.assertEqual(User.objects.count(), count)

    def test_unauthenticated_user_cannot_list_or_delete_team_users(self):
        organization, team, user = self.create_org_team_user()
        self.client.logout()

        response = self.client.get("/api/organization/member/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response_data: Dict = response.json()
        self.assertEqual(response_data, self.ERROR_RESPONSE_UNAUTHENTICATED)

        response = self.client.delete(f"/api/organization/member/{user.distinct_id}/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response_data = response.json()
        self.assertEqual(response_data, {"detail": "Authentication credentials were not provided."})


class TestTeamSignup(APIBaseTest):
    TESTS_EMAIL = None

    @tag("skip_on_multitenancy")
    @patch("posthog.api.team.settings.EE_AVAILABLE", False)
    @patch("posthog.api.team.MULTI_TENANCY_MISSING", False)
    @patch("posthog.api.team.posthoganalytics.identify")
    @patch("posthog.api.team.posthoganalytics.capture")
    def test_api_sign_up(self, mock_capture, mock_identify):
        response = self.client.post(
            "/api/organization/signup/",
            {
                "first_name": "John",
                "email": "hedgehog@posthog.com",
                "password": "notsecure",
                "company_name": "Hedgehogs United, LLC",
                "email_opt_in": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user: User = User.objects.order_by("-pk")[0]
        team: Team = user.team
        self.assertEqual(
            response.data,
            {"id": user.pk, "distinct_id": user.distinct_id, "first_name": "John", "email": "hedgehog@posthog.com"},
        )

        # Assert that the user was properly created
        self.assertEqual(user.first_name, "John")
        self.assertEqual(user.email, "hedgehog@posthog.com")
        self.assertEqual(user.email_opt_in, False)

        # Assert that the team was properly created
        self.assertEqual(team.name, "Hedgehogs United, LLC")

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id, "user signed up", properties={"is_first_user": True, "is_team_first_user": True},
        )

        mock_identify.assert_called_once_with(
            user.distinct_id, properties={"email": "hedgehog@posthog.com", "realm": "cloud", "ee_available": False},
        )

        # Assert that the user is logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "hedgehog@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("notsecure"))

    @tag("skip_on_multitenancy")
    @patch("posthog.api.team.posthoganalytics.capture")
    def test_sign_up_minimum_attrs(self, mock_capture):
        response = self.client.post(
            "/api/organization/signup/",
            {"first_name": "Jane", "email": "hedgehog2@posthog.com", "password": "notsecure",},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user: User = User.objects.order_by("-pk").get()
        team: Team = user.team
        self.assertEqual(
            response.data,
            {"id": user.pk, "distinct_id": user.distinct_id, "first_name": "Jane", "email": "hedgehog2@posthog.com",},
        )

        # Assert that the user was properly created
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.email, "hedgehog2@posthog.com")
        self.assertEqual(user.email_opt_in, True)  # Defaults to True
        self.assertEqual(team.name, "Jane")

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id, "user signed up", properties={"is_first_user": True, "is_team_first_user": True},
        )

        # Assert that the user is logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "hedgehog2@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("notsecure"))

    def test_cant_sign_up_without_required_attributes(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()

        required_attributes = [
            "first_name",
            "email",
            "password",
        ]

        for attribute in required_attributes:
            body = {
                "first_name": "Jane",
                "email": "invalid@posthog.com",
                "password": "notsecure",
            }
            body.pop(attribute)

            # Make sure the endpoint works with and without the trailing slash
            response = self.client.post("/api/organization/signup", body)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.data,
                {
                    "type": "validation_error",
                    "code": "required",
                    "detail": "This field is required.",
                    "attr": attribute,
                },
            )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)

    def test_cant_sign_up_with_short_password(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()

        response = self.client.post(
            "/api/organization/signup/", {"first_name": "Jane", "email": "failed@posthog.com", "password": "123",},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "type": "validation_error",
                "code": "password_too_short",
                "detail": "This password is too short. It must contain at least 8 characters.",
                "attr": "password",
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)

    @patch("posthog.api.team.MULTI_TENANCY_MISSING", False)
    def test_authenticated_user_cannot_signup_team(self):
        organization, team, user = User.objects.bootstrap(
            company_name="Test", email="i_was_first@posthog.com", first_name="X", password=None
        )
        self.client.force_login(user)

        count: int = User.objects.count()
        team_count: int = Team.objects.count()

        response = self.client.post(
            "/api/organization/signup/",
            {"first_name": "John", "email": "invalid@posthog.com", "password": "notsecure",},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Authenticated users may not create additional teams.",
                "attr": None,
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)

    @patch("posthog.api.team.MULTI_TENANCY_MISSING", True)
    def test_cant_create_multiple_teams_without_multitenancy(self):

        # Create a user first to make sure additional users CANT be created
        User.objects.create(email="i_was_first@posthog.com")

        count: int = User.objects.count()
        team_count: int = Team.objects.count()

        response = self.client.post(
            "/api/organization/signup/",
            {"first_name": "John", "email": "invalid@posthog.com", "password": "notsecure",},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "This instance does not support multiple teams.",
                "attr": None,
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
