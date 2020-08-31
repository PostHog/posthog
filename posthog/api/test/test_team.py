import random
from typing import Dict, List
from unittest.mock import patch

from django.db.models import Q
from rest_framework import status

from posthog.models import Team, User

from .base import APIBaseTest, BaseTest


class TestTeamUser(BaseTest):
    TESTS_API = True

    def create_user_for_team(self, team):
        suffix = random.randint(100, 999)
        user = User.objects.create_user(
            f"user{suffix}@posthog.com", password=self.TESTS_PASSWORD, first_name=f"User #{suffix}",
        )
        team.users.add(user)
        team.save()
        return user

    def create_team_and_user(self):
        team: Team = Team.objects.create(api_token="token123")
        return (team, self.create_user_for_team(team))

    def test_user_can_list_their_team_users(self):

        # Create a team with a list of multiple users first
        users: List = []
        team, user = self.create_team_and_user()
        users.append(user)
        for i in range(0, 3):
            users.append(self.create_user_for_team(team))

        self.client.force_login(random.choice(users))  # Log in as any of the users

        response = self.client.get("/api/team/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data: Dict = response.json()

        self.assertEqual(response_data["count"], 4)

        EXPECTED_ATTRS: List = ["id", "distinct_id", "first_name", "email"]
        user_ids: List = [x.distinct_id for x in users]

        for _user in response_data["results"]:
            self.assertEqual(list(_user.keys()), EXPECTED_ATTRS)

            self.assertIn(_user["distinct_id"], user_ids)  # Make sure only the correct users are returned

    def test_user_can_delete_another_team_user(self):
        team, user = self.create_team_and_user()
        user2: User = self.create_user_for_team(team)
        self.client.force_login(user)

        response = self.client.delete(f"/api/team/user/{user2.distinct_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(User.objects.get(id=user2.id).is_active)
        self.assertFalse(team.users.filter(Q(pk=user2.pk) | Q(distinct_id=user2.distinct_id)).exists())

    def test_cannot_delete_yourself(self):
        team, user = self.create_team_and_user()
        self.client.force_login(user)

        response = self.client.delete(f"/api/team/user/{user.distinct_id}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"detail": "Cannot delete yourself."})

        self.assertEqual(
            User.objects.filter(Q(pk=user.pk) | Q(distinct_id=user.distinct_id)).count(), 1,
        )  # User still exists

    def test_cannot_delete_user_using_their_primary_key(self):
        team, user = self.create_team_and_user()
        user2: User = self.create_user_for_team(team)
        self.client.force_login(user)

        response = self.client.delete(f"/api/team/user/{user2.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), {"detail": "Not found."})

        self.assertEqual(
            User.objects.filter(Q(pk=user2.pk) | Q(distinct_id=user2.distinct_id)).count(), 1,
        )  # User still exists

    def test_user_cannot_delete_user_from_another_team(self):
        team, user = self.create_team_and_user()
        self.client.force_login(user)

        team2, user2 = self.create_team_and_user()

        response = self.client.delete(f"/api/team/user/{user2.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), {"detail": "Not found."})

        self.assertEqual(
            User.objects.filter(Q(pk=user2.pk) | Q(distinct_id=user2.distinct_id)).count(), 1,
        )  # User still exists

    def test_creating_or_updating_users_is_currently_not_allowed(self):
        team, user = self.create_team_and_user()
        self.client.force_login(user)

        # Cannot partially update users
        email: str = user.email
        response = self.client.patch(
            f"/api/team/user/{user.distinct_id}/", {"email": "newemail@posthog.com"}, "application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(response.json(), {"detail": 'Method "PATCH" not allowed.'})

        # Cannot update users
        response = self.client.put(
            f"/api/team/user/{user.distinct_id}/", {"email": "newemail@posthog.com"}, "application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(response.json(), {"detail": 'Method "PUT" not allowed.'})

        user.refresh_from_db()
        self.assertEqual(user.email, email)

        # Cannot create users
        count: int = User.objects.count()
        response = self.client.post(
            f"/api/team/user/{user.distinct_id}/", {"email": "newuser@posthog.com"}, "application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(response.json(), {"detail": 'Method "POST" not allowed.'})
        self.assertEqual(User.objects.count(), count)

    def test_unauthenticated_user_cannot_list_or_delete_team_users(self):
        team, user = self.create_team_and_user()
        self.client.logout()

        response = self.client.get("/api/team/user/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response_data: Dict = response.json()
        self.assertEqual(response_data, {"detail": "Authentication credentials were not provided."})

        response = self.client.delete(f"/api/team/user/{user.distinct_id}/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        response_data = response.json()
        self.assertEqual(response_data, {"detail": "Authentication credentials were not provided."})


class TestTeamSignup(APIBaseTest):
    @patch("posthog.api.team.EE_MISSING", True)
    @patch("posthog.api.team.posthoganalytics.identify")
    @patch("posthog.api.team.posthoganalytics.capture")
    def test_can_sign_up_team(self, mock_capture, mock_identify):
        response = self.client.post(
            "/api/team/signup/",
            {
                "first_name": "John",
                "email": "hedgehog@posthog.com",
                "password": "notsecure",
                "company_name": "Hedgehogs United, LLC",
                "email_opt_in": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.last()
        team = user.team_set.first()
        self.assertEqual(
            response.data,
            {"id": user.pk, "distinct_id": user.distinct_id, "first_name": "John", "email": "hedgehog@posthog.com",},
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
            user.distinct_id, properties={"email": "hedgehog@posthog.com", "realm": "hosted", "ee_available": False},
        )

        # Assert that the user is logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "hedgehog@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("notsecure"))

    @patch("posthog.api.team.posthoganalytics.capture")
    def test_sign_up_minimum_attrs(self, mock_capture):
        response = self.client.post(
            "/api/team/signup/", {"first_name": "Jane", "email": "hedgehog2@posthog.com", "password": "notsecure",},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.last()
        team = user.team_set.first()
        self.assertEqual(
            response.data,
            {"id": user.pk, "distinct_id": user.distinct_id, "first_name": "Jane", "email": "hedgehog2@posthog.com",},
        )

        # Assert that the user was properly created
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.email, "hedgehog2@posthog.com")
        self.assertEqual(user.email_opt_in, True)  # Defaults to True
        self.assertEqual(team.name, "")

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

    @patch("posthog.api.team.MULTI_TENANCY_MISSING", False)
    @patch("posthog.api.team.posthoganalytics.identify")
    @patch("posthog.api.team.posthoganalytics.capture")
    def test_sign_up_multiple_teams_multi_tenancy(self, mock_capture, mock_identify):

        # Create a user first to make sure additional users can be created
        User.objects.create(email="i_was_first@posthog.com")

        response = self.client.post(
            "/api/team/signup/", {"first_name": "John", "email": "multi@posthog.com", "password": "eruceston",},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.last()
        self.assertEqual(
            response.data,
            {"id": user.pk, "distinct_id": user.distinct_id, "first_name": "John", "email": "multi@posthog.com",},
        )

        # Assert that the user was properly created
        self.assertEqual(user.first_name, "John")
        self.assertEqual(user.email, "multi@posthog.com")

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id, "user signed up", properties={"is_first_user": False, "is_team_first_user": True},
        )

        mock_identify.assert_called_once_with(
            user.distinct_id, properties={"email": "multi@posthog.com", "realm": "cloud", "ee_available": True},
        )

        # Assert that the user is logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "multi@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("eruceston"))

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
            response = self.client.post("/api/team/signup/", body)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data, {attribute: ["This field is required."]})

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)

    def test_cant_sign_up_with_short_password(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()

        response = self.client.post(
            "/api/team/signup/", {"first_name": "Jane", "email": "failed@posthog.com", "password": "123",},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data, {"password": ["This password is too short. It must contain at least 8 characters."]}
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)

    @patch("posthog.api.team.MULTI_TENANCY_MISSING", False)
    def test_authenticated_user_cannot_signup_team(self):
        user = User.objects.create(email="i_was_first@posthog.com")
        self.client.force_login(user)

        count: int = User.objects.count()
        team_count: int = Team.objects.count()

        response = self.client.post(
            "/api/team/signup/", {"first_name": "John", "email": "invalid@posthog.com", "password": "notsecure",},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, ["Authenticated users may not create additional teams."])

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)

    def test_cant_create_multiple_teams_without_multitenancy_or_enterprise(self):

        # Create a user first to make sure additional users CANT be created
        User.objects.create(email="i_was_first@posthog.com")

        count: int = User.objects.count()
        team_count: int = Team.objects.count()

        response = self.client.post(
            "/api/team/signup/", {"first_name": "John", "email": "invalid@posthog.com", "password": "notsecure",},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, ["This instance does not support multiple teams."])

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
