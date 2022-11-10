import json
from typing import Any, Dict, List, Optional

from dateutil import parser
from rest_framework import exceptions, request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.client import query_with_columns
from posthog.models.prompt.constants import prompts_config
from posthog.models.prompt.prompt import UserPromptSequenceState

SELECT_PROMPT_TRIGGER_SQL = """
SELECT
    event,
    properties,
    timestamp
FROM events
WHERE
team_id = %(team_id)s
AND event = 'prompt trigger'
AND events.distinct_id in [%(distinct_id)s]
ORDER BY timestamp DESC
LIMIT 101
"""

# Take a "prompt trigger" event and build a prompt sequence out of the event parameters
def event_properties_to_prompt_sequence(properties: Dict) -> Dict[str, Any]:
    try:
        if not properties.get("text") or not properties.get("key"):
            return None
        sequence: Dict = {
            "key": properties["key"],
        }
        # TODO extend type
        prompt = {"step": 0, "type": "tooltip", "text": properties["text"]}
        if properties.get("title"):
            prompt["title"] = properties["title"]
        if properties.get("buttons"):
            buttons = []
            for button in properties["buttons"]:
                if not button.get("label") or (not button.get("url") and not button.get("action")):
                    continue
                if button.get("url"):
                    buttons.append(
                        {
                            "url": button["url"],
                            "label": button["label"],
                        }
                    )
                if button.get("action"):
                    buttons.append(
                        {
                            "action": button["action"],
                            "label": button["label"],
                        }
                    )
            prompt["buttons"] = buttons
        prompt["placement"] = properties.get("placement", "bottom-start")
        if properties.get("reference"):
            prompt["reference"] = properties["reference"]
        sequence["prompts"] = [prompt]
        sequence["rule"] = {"path": {"must_match": ["/*"]}}
        return sequence
    except Exception:
        return None


# Take the hardcoded "prompts_config" sequences and append event-based sequences
def get_active_prompt_sequences(distinct_id: str, team_id: str) -> List[Dict[str, Any]]:

    active_prompts = prompts_config
    prompt_events = query_with_columns(SELECT_PROMPT_TRIGGER_SQL, {"distinct_id": distinct_id, "team_id": team_id})
    prompt_keys = set()
    for event in prompt_events:
        prompt = event_properties_to_prompt_sequence(json.loads(event["properties"]))
        if prompt["key"] not in prompt_keys:
            prompt_keys.add(prompt["key"])
            active_prompts.append(prompt)

    return active_prompts


class PromptSequenceStateSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = UserPromptSequenceState
        fields = ["key", "last_updated_at", "step", "completed", "dismissed"]


class PromptSequenceStateViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    """
    Create, read, update and delete prompt sequences state for a person.
    """

    serializer_class = PromptSequenceStateSerializer

    @action(methods=["PATCH"], detail=False)
    def my_prompts(self, request: request.Request, **kwargs):
        if not request.user.is_authenticated:  # for mypy otherwise check on distict_id below fails
            raise exceptions.NotAuthenticated()
        local_states: List[Dict[str, Any]] = []
        local_state_keys = set()
        for key in request.data:
            if key not in local_state_keys:
                parsed_state = dict(
                    request.data[key], last_updated_at=parser.isoparse(request.data[key]["last_updated_at"])
                )
                local_states.append(parsed_state)
                local_state_keys.add(key)

        my_prompts: Dict[str, Any] = {"sequences": [], "state": {}}
        states_to_update: List[UserPromptSequenceState] = []
        states_to_create: List[UserPromptSequenceState] = []

        saved_states = UserPromptSequenceState.objects.filter(user=request.user)
        all_sequences = get_active_prompt_sequences(request.user.email, request.user.team.id)

        new_states: List[Dict] = []

        for sequence in all_sequences:
            local_state = next((s for s in local_states if sequence["key"] == s["key"]), None)
            saved_state: Optional[UserPromptSequenceState] = next(
                (s for s in saved_states if sequence["key"] == s.key), None
            )

            state = None
            # check if the local state is more recent than the one in the db, then update accordingly
            if local_state:
                if saved_state and local_state["last_updated_at"] > saved_state.last_updated_at:
                    saved_state.last_updated_at = local_state["last_updated_at"]
                    saved_state.step = local_state["step"]
                    saved_state.completed = local_state.get("completed", False)
                    saved_state.dismissed = local_state.get("dismissed", False)
                    states_to_update.append(saved_state)
                    state = local_state
                elif saved_state is None:
                    state = local_state
                    new_state = UserPromptSequenceState(user=request.user, **local_state)
                    states_to_create.append(new_state)

            if not state and saved_state:
                state = PromptSequenceStateSerializer(saved_state).data

            if state:
                new_states.append(state)
                my_prompts["state"][sequence["key"]] = state

        # filter only the sequences where `must_be_completed` rule passes
        sequences = [x for x in all_sequences if not x["rule"].get("must_be_completed")]
        sequences_requiring_previous_completion = [x for x in all_sequences if x["rule"].get("must_be_completed")]

        for seq in sequences_requiring_previous_completion:
            must_be_completed = seq["rule"]["must_be_completed"]
            current_state: Optional[Dict] = next((s for s in new_states if s["key"] in must_be_completed), None)
            if not current_state or not current_state["completed"]:
                continue
            sequences.append(seq)

        my_prompts["sequences"] = sequences

        if states_to_create:
            UserPromptSequenceState.objects.bulk_create(states_to_create)
        if states_to_update:
            UserPromptSequenceState.objects.bulk_update(
                states_to_update, ["last_updated_at", "step", "completed", "dismissed"]
            )

        return Response(my_prompts)
