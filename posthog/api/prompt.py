from typing import Any, Dict, List, Optional

from dateutil import parser
from rest_framework import exceptions, request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.person.person import PersonDistinctId
from posthog.models.prompt import PromptSequenceState, get_active_prompt_sequences


class PromptSequenceStateSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = PromptSequenceState
        read_only_fields = ["key", "last_updated_at", "step", "completed", "dismissed"]


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
        for key in request.data:
            parsed_state = dict(
                request.data[key], last_updated_at=parser.isoparse(request.data[key]["last_updated_at"])
            )
            local_states.append(parsed_state)

        my_prompts: Dict[str, Any] = {"sequences": [], "state": {}}
        states_to_update: List[PromptSequenceState] = []
        states_to_create: List[PromptSequenceState] = []

        person_id = (
            PersonDistinctId.objects.filter(distinct_id=request.user.distinct_id, team_id=self.team_id)
            .values_list("person_id", flat=True)
            .first()
        )

        if not person_id:
            raise exceptions.NotFound()

        saved_states = PromptSequenceState.objects.filter(team=self.team, person_id=person_id)
        all_sequences = get_active_prompt_sequences()

        new_states: List[Dict] = []

        for sequence in all_sequences:
            local_state = next((s for s in local_states if sequence["key"] == s["key"]), None)
            saved_state: Optional[PromptSequenceState] = next(
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
                    new_state = PromptSequenceState(team=self.team, person_id=person_id, **local_state)
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
            PromptSequenceState.objects.bulk_create(states_to_create)
        if states_to_update:
            PromptSequenceState.objects.bulk_update(
                states_to_update, ["last_updated_at", "step", "completed", "dismissed"]
            )

        return Response(my_prompts)
