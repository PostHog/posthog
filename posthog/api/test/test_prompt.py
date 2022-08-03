from typing import Dict, List

from freezegun.api import freeze_time
from rest_framework import status

from posthog.models import User
from posthog.models.person.person import Person
from posthog.models.prompt import PromptSequenceState, experiment_config
from posthog.models.team.team import Team
from posthog.test.base import APIBaseTest


class TestPrompt(APIBaseTest):
    sequences: List[Dict] = experiment_config

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    @freeze_time("2022-08-25T22:09:14.252Z")
    def test_my_prompts(self):

        distinct_id_user = User.objects.create_and_join(self.organization, "distinct_id_user@posthog.com", None)
        distinct_id_user.distinct_id = "distinct_id"
        distinct_id_user.save()
        self.client.force_login(distinct_id_user)
        person = Person.objects.create(
            team=self.team, is_user=distinct_id_user, distinct_ids=[distinct_id_user.distinct_id]
        )

        # receive only the one sequence which doesn't have prerequisites
        response = self.client.patch(f"/api/projects/{self.team.id}/prompts/my_prompts", {}, format="json",)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = response.json()
        self.assertEqual(len(json_response["sequences"]), 1)
        self.assertEqual(json_response["sequences"][0]["key"], self.sequences[0]["key"])

        # updates the saved state using the more recent local state
        local_state = {
            "start-flow": {
                "key": "start-flow",
                "last_updated_at": "2022-08-25T22:09:14.252Z",
                "step": 0,
                "completed": True,
                "dismissed": False,
            }
        }
        response = self.client.patch(f"/api/projects/{self.team.id}/prompts/my_prompts", local_state, format="json",)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = response.json()
        # we now also receive the other sequences
        self.assertEqual(len(json_response["sequences"]), len(self.sequences))
        self.assertEqual(json_response["state"]["start-flow"]["step"], 0)
        self.assertEqual(json_response["state"]["start-flow"]["completed"], True)

        saved_states = list(PromptSequenceState.objects.filter(team=self.team, person_id=person.id))
        self.assertEqual(len(saved_states), 1)
        first_saved_state = list(saved_states)[0]
        self.assertEqual(first_saved_state.step, 0)
        self.assertEqual(first_saved_state.completed, True)

        # ignores the local state as it is less recent
        local_state = {
            "start-flow": {
                "key": "start-flow",
                "last_updated_at": "2022-08-24T22:09:14.252Z",
                "step": 1,
                "completed": False,
                "dismissed": False,
            }
        }
        response = self.client.patch(f"/api/projects/{self.team.id}/prompts/my_prompts", local_state, format="json",)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = response.json()
        self.assertEqual(json_response["state"]["start-flow"]["step"], 0)
        self.assertEqual(json_response["state"]["start-flow"]["completed"], True)

    def test_cant_read_prompts_viewed_for_another_team(self):
        distinct_id_user = User.objects.create_and_join(self.organization, "distinct_id_user@posthog.com", None)
        distinct_id_user.distinct_id = "distinct_id"
        distinct_id_user.save()
        self.client.force_login(distinct_id_user)
        person = Person.objects.create(
            team=self.team, is_user=distinct_id_user, distinct_ids=[distinct_id_user.distinct_id]
        )

        other_team = Team.objects.create(organization=self.organization, name="other team")
        local_state = {
            "start-flow": {
                "key": "start-flow",
                "last_updated_at": "2021-08-25T22:09:14.252Z",
                "step": 0,
                "completed": True,
                "dismissed": False,
            }
        }
        response = self.client.patch(f"/api/projects/{other_team.id}/prompts/my_prompts", local_state, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        saved_states = list(PromptSequenceState.objects.filter(team=self.team, person_id=person.id))
        self.assertEqual(len(saved_states), 0)
