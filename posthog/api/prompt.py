from typing import Any, Dict, List

from dateutil import parser
from rest_framework import exceptions, request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.prompt import Prompt, PromptSequence, UserPromptState


class PromptButtonSerializer(serializers.Serializer):
    label = serializers.CharField()
    url = serializers.CharField(required=False)
    action = serializers.CharField(required=False)


class PromptSerializer(serializers.ModelSerializer):
    buttons = PromptButtonSerializer(many=True, required=False)

    class Meta:
        model = Prompt
        fields = ["step", "type", "title", "text", "placement", "reference", "buttons"]


class PromptSequenceSerializer(serializers.ModelSerializer):
    prompts = PromptSerializer(many=True)

    class Meta:
        model = PromptSequence
        fields = ["key", "path_match", "path_exclude", "type", "status", "prompts"]


class UserPromptStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPromptState
        fields = ["last_updated_at", "step", "completed", "dismissed"]


class PromptSequenceStateViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    """
    Create, read, update and delete prompt sequences state for a person.
    """

    @action(methods=["PATCH"], detail=False)
    def my_prompts(self, request: request.Request, **kwargs):
        if not request.user.is_authenticated:  # for mypy otherwise check on distict_id below fails
            raise exceptions.NotAuthenticated()
        local_states: List[UserPromptState] = []
        local_state_keys = set()
        all_sequences = PromptSequence.objects.filter(status="active")
        for key in request.data:
            if key not in local_state_keys:
                sequence = all_sequences.get(key=key)
                if not sequence:
                    continue
                parsed_state: Dict[str, Any] = dict(
                    request.data[key],
                    last_updated_at=parser.isoparse(request.data[key]["last_updated_at"]),
                    sequence=sequence,
                )
                local_states.append(
                    UserPromptState(
                        user=request.user,
                        **parsed_state,
                    )
                )
                local_state_keys.add(key)  # prevent duplicates

        states_to_update: List[UserPromptState] = []
        states_to_create: List[UserPromptState] = []

        saved_states = UserPromptState.objects.filter(user=request.user)
        up_to_date_states: List[UserPromptState] = []

        for sequence in all_sequences:
            local_state = next((s for s in local_states if sequence == s.sequence), None)
            saved_state = next((s for s in saved_states if sequence == s.sequence), None)

            state = None
            # check if the local state is more recent than the one in the db, then update accordingly
            if local_state:
                if saved_state and local_state.last_updated_at > saved_state.last_updated_at:
                    saved_state.last_updated_at = local_state.last_updated_at
                    saved_state.step = local_state.step
                    saved_state.completed = local_state.completed
                    saved_state.dismissed = local_state.dismissed
                    states_to_update.append(saved_state)
                    state = saved_state
                elif saved_state is not None:
                    state = saved_state
                else:
                    states_to_create.append(local_state)
                    state = local_state
            else:
                if saved_state:
                    state = saved_state
                # if the sequence should autorun for all users, we create a state with no step, meaning the user has not seen it but should start seeing it
                elif sequence.autorun:
                    state = UserPromptState(user=request.user, sequence=sequence, step=None)

            if state:
                up_to_date_states.append(state)

        my_prompts: Dict[str, Any] = {"state": {}, "sequences": []}
        # filter only the sequences where `must_be_completed` rule passes
        for state in up_to_date_states:
            sequence = state.sequence
            must_have_completed = sequence.must_have_completed.all()
            if len(must_have_completed) > 0:
                current_state = next((s for s in up_to_date_states if s.sequence in must_have_completed), None)
                if not current_state or (current_state and not current_state.completed):
                    continue
            my_prompts["state"][sequence.key] = UserPromptStateSerializer(state).data
            my_prompts["sequences"].append(PromptSequenceSerializer(sequence).data)

        if states_to_create:
            UserPromptState.objects.bulk_create(states_to_create)
        if states_to_update:
            UserPromptState.objects.bulk_update(states_to_update, ["last_updated_at", "step", "completed", "dismissed"])

        return Response(my_prompts)
