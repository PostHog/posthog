import random
from typing import Dict, List

from django.db.models import Q
from rest_framework import status

from posthog.models import Team, User

from .base import BaseTest


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

    def test_user_can_list_their_teams(self):

        # Create a team with a list of multiple users first
        teams: List = []
        for i in range(0, 3):
            team = Team.objects.create(name="app" + str(i), api_token="token1234" + str(i))
            team.users.add(self.user)
            teams.append(team)

        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data: Dict = response.json()

        self.assertEqual(len(response_data["teams"]), 4)

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

    def test_user_can_change_current_team(self):
        team1: Team = Team.objects.create(name="app1", api_token="EIN")
        team2: Team = Team.objects.create(name="app2", api_token="ZWEI")
        team1.users.add(self.user)
        team1.save()
        team2.users.add(self.user)
        team2.save()

        response = self.client.patch(
            "/api/user/", data={"user": {"current_team_id": team2.id}}, content_type="application/json",
        ).json()
        self.assertEqual(response["team"]["name"], "app2")
        self.assertEqual(response["team"]["api_token"], "ZWEI")

    def test_user_cannot_switch_to_unavailable_team(self):
        team1: Team = Team.objects.create(name="app1", api_token="token1234")

        response = self.client.patch(
            "/api/user/", data={"user": {"current_team_id": team1.id}}, content_type="application/json",
        ).json()
        self.assertEqual(response.status_code, 404)

        response = self.client.patch(
            "/api/user/", data={"user": {"current_team_id": 54353453}}, content_type="application/json",
        ).json()
        self.assertEqual(response.status_code, 404)

    def test_user_can_only_switch_teams_with_id(self):
        response = self.client.patch(
            "/api/user/", data={"user": {"current_team_id": "abc"}}, content_type="application/json",
        ).json()
        self.assertEqual(response.status_code, 400)

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
