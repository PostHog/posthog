from freezegun.api import freeze_time
from rest_framework import status

from posthog.models import User
from posthog.models.prompt import Prompt, PromptSequence, UserPromptState
from posthog.test.base import APIBaseTest


def _setup_prompts() -> None:
    prompt1 = Prompt.objects.create(
        step=0,
        type="tooltip",
        title="Welcome to PostHog!",
        text="We have prepared a list of suggestions and resources to improve your experience with the tool. You can access it at any time by clicking on the question mark icon in the top right corner of the screen, and then selecting 'How to be successful with PostHog'.",
        placement="bottom-start",
        reference="help-button",
        buttons=[{"action": "activation-checklist", "label": "Show me suggestions"}],
    )
    sequence1 = PromptSequence.objects.create(
        key="start-flow",
        type="one-off",
        path_match=["/*"],
        path_exclude=["/ingestion", "/ingestion/*"],
        status="active",
    )
    sequence1.prompts.add(prompt1)

    prompt2 = Prompt.objects.create(
        step=0,
        type="tooltip",
        title="Track your marketing websites",
        text="PostHog may have been built for product analytics, but that doesn’t mean you can only deploy it on your core product — you can also use it to gather analytics from your marketing website too.",
        placement="bottom-start",
        reference="help-button",
        buttons=[
            {
                "url": "https://posthog.com/blog/how-and-why-track-your-website-with-posthog",
                "label": "How (and why) to track your website with PostHog",
            }
        ],
    )
    sequence2 = PromptSequence.objects.create(
        key="activation-checklist",
        type="one-off",
        path_match=["/*"],
        path_exclude=["/ingestion", "/ingestion/*"],
        status="active",
    )
    sequence2.prompts.add(prompt2)
    sequence2.must_have_completed.add(sequence1)


_webhook_prompt = {
    "key": "start-flow",
    "prompts": [
        {
            "step": 0,
            "title": "Welcome to PostHog!",
            "text": "We have prepared a list of suggestions and resources to improve your experience with the tool. You can access it at any time by clicking on the question mark icon in the top right corner of the screen, and then selecting 'How to be successful with PostHog'.",
        }
    ],
}


class TestPrompt(APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    def setUp(cls):
        distinct_id_user = User.objects.create_and_join(cls.organization, "distinct_id_user@posthog.com", None)
        distinct_id_user.distinct_id = "distinct_id"
        distinct_id_user.save()
        cls.user = distinct_id_user

    @freeze_time("2022-08-25T22:09:14.252Z")
    def test_my_prompts(self):
        self.client.force_login(self.user)
        _setup_prompts()
        # receive only the one sequence which doesn't have prerequisites
        response = self.client.patch(f"/api/prompts/my_prompts", {}, format="json")
        assert response.status_code == status.HTTP_200_OK
        json_response = response.json()
        assert len(json_response["sequences"]) == 1
        assert json_response["sequences"][0]["key"] == "start-flow"

        # updates the saved state using the more recent local state
        local_state = {
            "start-flow": {
                "sequence": "start-flow",
                "last_updated_at": "2022-08-25T22:09:14.252Z",
                "step": 0,
                "completed": True,
                "dismissed": False,
            }
        }
        response = self.client.patch(f"/api/prompts/my_prompts", local_state, format="json")
        assert response.status_code == status.HTTP_200_OK
        json_response = response.json()
        # we now also receive the other sequences, as the first one has been marked as completed
        assert len(json_response["sequences"]) == 2
        assert json_response["state"]["start-flow"]["step"] == 0
        assert json_response["state"]["start-flow"]["completed"] is True

        saved_states = list(UserPromptState.objects.filter(user=self.user))
        assert len(saved_states) == 1
        first_saved_state = list(saved_states)[0]
        assert first_saved_state.step == 0
        assert first_saved_state.completed is True

        # ignores the local state as it is less recent
        local_state = {
            "start-flow": {
                "sequence": "start-flow",
                "last_updated_at": "2022-08-24T22:09:14.252Z",
                "step": 1,
                "completed": False,
                "dismissed": False,
            }
        }
        response = self.client.patch(f"/api/prompts/my_prompts", local_state, format="json")
        assert response.status_code == status.HTTP_200_OK
        json_response = response.json()
        assert len(json_response["sequences"]) == 2
        assert json_response["state"]["start-flow"]["step"] == 0
        assert json_response["state"]["start-flow"]["completed"] is True

    def test_webhook_rejects_missing_token(self):
        # we send a webhook with a new sequence, but it's missing an api_token so it should get rejected
        webhook_data = {
            "emails": [],
            "sequence": _webhook_prompt,
        }
        response = self.client.post("/api/prompts/webhook", webhook_data, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_webhook_rejects_get_request(self):
        # we send a webhook with a GET call so it should get rejected
        response = self.client.get("/api/prompts/webhook", format="json")
        assert response.json()["code"] == "no_data"
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_webhook_invalid_data(self):
        # we send a webhook with invalid data so it should get rejected
        webhook_data = {
            "api_key": self.team.api_token,
            "emails": self.user.email,  # this should be a list
            "sequence": {  # key is missing
                "type": "one-off",
                "path_match": ["/*"],
                "status": "active",
                "path_exclude": ["/ingestion", "/ingestion/*"],
                "prompts": [
                    {
                        "step": 0,
                        "type": "tooltip",
                        "title": "Welcome to PostHog!",
                        "text": "We have prepared a list of suggestions and resources to improve your experience with the tool. You can access it at any time by clicking on the question mark icon in the top right corner of the screen, and then selecting 'How to be successful with PostHog'.",
                        "placement": "bottom-start",
                        "reference": "help-button",
                        "buttons": [
                            {
                                "action": "activation-checklist",
                                "label": "Show me suggestions",
                            }
                        ],
                    }
                ],
            },
        }
        response = self.client.post("/api/prompts/webhook", webhook_data, format="json")
        assert response.json()["code"] == "invalid"
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_webhook_creates_sequence_and_state(self):
        # we send a webhook with a new sequence, and we want to trigger it for a user
        webhook_data = {
            "api_key": self.team.api_token,
            "emails": [self.user.email],
            "sequence": _webhook_prompt,
        }

        # there is no sequence or prompt saved yet
        saved_sequences = list(PromptSequence.objects.all())
        assert len(saved_sequences) == 0
        saved_prompts = list(Prompt.objects.all())
        assert len(saved_prompts) == 0

        response = self.client.post("/api/prompts/webhook", webhook_data, format="json")
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json() == {"success": True}

        # assert that the sequence and prompt have been saved correctly matching the webhook data
        saved_prompts = list(Prompt.objects.all())
        assert len(saved_prompts) == 1
        first_saved_prompt = list(saved_prompts)[0]
        assert first_saved_prompt.step == 0
        assert first_saved_prompt.type == "tooltip"
        assert first_saved_prompt.title == "Welcome to PostHog!"
        assert (
            first_saved_prompt.text
            == "We have prepared a list of suggestions and resources to improve your experience with the tool. You can access it at any time by clicking on the question mark icon in the top right corner of the screen, and then selecting 'How to be successful with PostHog'."
        )
        assert first_saved_prompt.placement == "top"
        assert first_saved_prompt.reference is None
        assert first_saved_prompt.buttons == []

        saved_sequences = list(PromptSequence.objects.all())
        assert len(saved_sequences) == 1
        first_saved_sequence = list(saved_sequences)[0]
        assert first_saved_sequence.key == "start-flow"
        assert first_saved_sequence.type == "one-off"
        assert first_saved_sequence.path_match == ["/*"]
        assert first_saved_sequence.path_exclude == []
        assert first_saved_sequence.status == "active"
        assert first_saved_sequence.autorun is False
        assert first_saved_sequence.must_have_completed.count() == 0
        assert first_saved_prompt in first_saved_sequence.prompts.all()

        # assert that the user prompt state has been created correctly, with step = None so that it triggers the first prompt on first load
        saved_states = list(UserPromptState.objects.filter(user=self.user))
        assert len(saved_states) == 1
        first_saved_state = list(saved_states)[0]
        assert first_saved_state.sequence == first_saved_sequence
        assert first_saved_state.step is None
        assert first_saved_state.completed is False
