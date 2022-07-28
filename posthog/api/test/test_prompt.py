from freezegun.api import freeze_time
from rest_framework import status

from posthog.models import User
from posthog.models.person.person import Person
from posthog.models.prompt import PromptSequenceState, get_active_prompt_sequences
from posthog.test.base import APIBaseTest


class TestPrompt(APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.prompt_sequences = get_active_prompt_sequences()

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_my_prompts(self):

        distinct_id_user = User.objects.create_and_join(self.organization, "distinct_id_user@posthog.com", None)
        distinct_id_user.distinct_id = "distinct_id"
        distinct_id_user.save()
        self.client.force_login(distinct_id_user)
        person = Person.objects.create(
            team=self.team, is_user=distinct_id_user, distinct_ids=[distinct_id_user.distinct_id]
        )

        # updates the saved state using the more recent local state
        local_state = {
            "experiment-events-product-tour": {
                "key": "experiment-events-product-tour",
                "last_updated_at": "2021-08-25T22:09:14.252Z",
                "step": 1,
                "completed": False,
                "dismissed": True,
            }
        }
        response = self.client.patch(f"/api/projects/{self.team.id}/prompts/my_prompts", local_state, format="json",)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = response.json()
        self.assertEqual(json_response["sequences"][0]["key"], self.prompt_sequences[0]["key"])
        self.assertEqual(json_response["state"]["experiment-events-product-tour"]["step"], 1)
        self.assertEqual(json_response["state"]["experiment-events-product-tour"]["dismissed"], True)

        saved_states = list(PromptSequenceState.objects.filter(team=self.team, person_id=person.id))
        self.assertEqual(len(saved_states), 1)
        first_saved_state = list(saved_states)[0]
        self.assertEqual(first_saved_state.step, 1)
        self.assertEqual(first_saved_state.dismissed, True)

        # ignores the local state as it is less recent
        local_state = {
            "experiment-events-product-tour": {
                "key": "experiment-events-product-tour",
                "last_updated_at": "2021-08-24T22:09:14.252Z",
                "step": 0,
                "completed": False,
                "dismissed": False,
            }
        }
        response = self.client.patch(f"/api/projects/{self.team.id}/prompts/my_prompts", local_state, format="json",)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json_response = response.json()
        self.assertEqual(json_response["state"]["experiment-events-product-tour"]["step"], 1)
        self.assertEqual(json_response["state"]["experiment-events-product-tour"]["dismissed"], True)
