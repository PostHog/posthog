from typing import Any, List

from dateutil import parser
from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.person.person import PersonDistinctId
from posthog.models.prompt import PromptSequenceState, get_active_prompt_sequences


class PromptSequenceStateSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = PromptSequenceState
        fields = ["key", "last_updated_at", "step", "completed", "dismissed"]


class PromptSequenceStateViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    """
    Create, read, update and delete prompt sequences state for a person.
    """

    serializer_class = PromptSequenceStateSerializer

    @action(methods=["PATCH"], detail=False)
    def my_prompts(self, request: request.Request, **kwargs):
        local_states = []
        for key in request.data:
            parsed_state = dict(
                request.data[key], last_updated_at=parser.isoparse(request.data[key]["last_updated_at"])
            )
            local_states.append(parsed_state)

        all_sequences = get_active_prompt_sequences()
        my_prompts: dict[str, Any] = {"sequences": [], "state": {}}
        states_to_update: List[dict] = []
        states_to_create: List[dict] = []

        person_id = (
            PersonDistinctId.objects.filter(distinct_id=request.user.distinct_id, team_id=self.team_id)
            .values_list("person_id", flat=True)
            .first()
        )

        saved_states = PromptSequenceState.objects.filter(team=self.team, person_id=person_id)
        for sequence in all_sequences:
            local_state = next((s for s in local_states if sequence["key"] == s["key"]), None)
            saved_state: PromptSequenceState = next((s for s in saved_states if sequence["key"] == s.key), None)

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
                    states_to_create.append(PromptSequenceState(team=self.team, person_id=person_id, **local_state))

            if not state and saved_state:
                state = PromptSequenceStateSerializer(saved_state).data

            my_prompts["sequences"].append(sequence)
            if state:
                my_prompts["state"][sequence["key"]] = state

        if states_to_create:
            PromptSequenceState.objects.bulk_create(states_to_create)
        if states_to_update:
            PromptSequenceState.objects.bulk_update(
                states_to_update, ["last_updated_at", "step", "completed", "dismissed"]
            )

        return Response(my_prompts)
