import json
from typing import Any, Dict, List

from dateutil import parser
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import exceptions, request, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.utils import get_token
from posthog.celery import app
from posthog.exceptions import generate_exception_response
from posthog.models.prompt import Prompt, PromptSequence, UserPromptState
from posthog.models.user import User
from posthog.utils_cors import cors_response


class PromptButtonSerializer(serializers.Serializer):
    label = serializers.CharField()  # type: ignore
    url = serializers.CharField(required=False)
    action = serializers.CharField(required=False)


class PromptSerializer(serializers.ModelSerializer):
    buttons = PromptButtonSerializer(many=True, required=False, default=[])
    reference = serializers.CharField(default=None)
    placement = serializers.CharField(default="top")
    type = serializers.CharField(default="tooltip")

    class Meta:
        model = Prompt
        fields = ["step", "type", "title", "text", "placement", "reference", "buttons"]


class PromptSequenceSerializer(serializers.ModelSerializer):
    prompts = PromptSerializer(many=True)
    path_match = serializers.ListField(child=serializers.CharField(), default=["/*"])
    path_exclude = serializers.ListField(child=serializers.CharField(), default=[])
    status = serializers.CharField(default="active")
    requires_opt_in = serializers.BooleanField(default=False)
    type = serializers.CharField(default="one-off")
    autorun = serializers.BooleanField(default=False)

    class Meta:
        model = PromptSequence
        fields = [
            "key",
            "path_match",
            "path_exclude",
            "requires_opt_in",
            "type",
            "status",
            "prompts",
            "autorun",
        ]


class UserPromptStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPromptState
        fields = ["last_updated_at", "step", "completed", "dismissed"]


class PromptSequenceViewSet(StructuredViewSetMixin, viewsets.ViewSet):
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
        # get the local state (sent from localstorage), and filter it based on active sequences
        for key in request.data:
            if key not in local_state_keys:
                try:
                    sequence = all_sequences.get(key=key)
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
                except:
                    continue

        states_to_update: List[UserPromptState] = []
        states_to_create: List[UserPromptState] = []

        saved_states = UserPromptState.objects.filter(user=request.user)
        up_to_date_states: List[UserPromptState] = []

        # for each sequence, we check if either the local state, or the one saved in the db is more up to date
        # if the local state is more up to date, we update the db state
        # if the db state is more up to date, we send it back to the frontend
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
        # this allows to run certain sequences only if other have been completed first
        for state in up_to_date_states:
            sequence = state.sequence
            must_have_completed = sequence.must_have_completed.all()
            if len(must_have_completed) > 0:
                current_state = next(
                    (s for s in up_to_date_states if s.sequence in must_have_completed),
                    None,
                )
                if not current_state or (current_state and not current_state.completed):
                    continue
            my_prompts["state"][sequence.key] = UserPromptStateSerializer(state).data
            my_prompts["sequences"].append(PromptSequenceSerializer(sequence).data)

        # update or create any state to db
        if states_to_create:
            UserPromptState.objects.bulk_create(states_to_create)
        if states_to_update:
            UserPromptState.objects.bulk_update(states_to_update, ["last_updated_at", "step", "completed", "dismissed"])

        return Response(my_prompts)


class WebhookSerializer(serializers.Serializer):
    sequence = PromptSequenceSerializer()
    emails = serializers.ListField(child=serializers.EmailField(), required=False)


class WebhookSequenceSerializer(serializers.ModelSerializer):
    path_match = serializers.ListField(child=serializers.CharField(), default=["/*"])
    path_exclude = serializers.ListField(child=serializers.CharField(), default=[])
    requires_opt_in = serializers.BooleanField(default=False)
    status = serializers.CharField(default="active")
    autorun = serializers.BooleanField(default=False)
    type = serializers.CharField(default="one-off")

    class Meta:
        model = PromptSequence
        fields = [
            "key",
            "path_match",
            "path_exclude",
            "type",
            "status",
            "requires_opt_in",
            "autorun",
        ]


@app.task(ignore_result=True)
def trigger_prompt_for_user(email: str, sequence_id: int):
    try:
        sequence = PromptSequence.objects.get(pk=sequence_id)
        user = User.objects.get(email=email)
        UserPromptState.objects.get_or_create(user=user, sequence=sequence, step=None)
    except (User.DoesNotExist, IntegrityError):
        pass


@csrf_exempt
def prompt_webhook(request: request.Request):
    if request.method == "POST":
        data = json.loads(request.body)
    else:
        return cors_response(
            request,
            generate_exception_response(
                "prompts_webhook",
                "No data found. Make sure to use a POST request when sending the payload in the body of the request.",
                code="no_data",
            ),
        )

    token = get_token(data, request)

    if not token:
        return cors_response(
            request,
            generate_exception_response(
                "prompts_webhook",
                "API key not provided. You can find your project API key in PostHog project settings.",
                type="authentication_error",
                code="missing_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    serializer = WebhookSerializer(data=data)
    if not serializer.is_valid():
        return cors_response(
            request,
            generate_exception_response(
                "prompts_webhook",
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
        )
    serialized_data = serializer.validated_data

    prompt_data = []
    for prompt in serialized_data["sequence"]["prompts"]:
        prompt_data.append(PromptSerializer(prompt).data)

    # get or create sequence from webhook
    sequence_data = WebhookSequenceSerializer(serialized_data["sequence"]).data
    try:
        sequence = PromptSequence.objects.get(key=sequence_data["key"])
    except PromptSequence.DoesNotExist:
        sequence = PromptSequence.objects.create(**sequence_data)
        for prompt in prompt_data:
            new_prompt = Prompt.objects.create(**prompt)
            sequence.prompts.add(new_prompt)

    # trigger the sequence for users matching the emails, by creating empty states for them
    if serialized_data.get("emails"):
        for email in serialized_data["emails"]:
            trigger_prompt_for_user.delay(email, sequence.id)

    return cors_response(request, JsonResponse(status=status.HTTP_202_ACCEPTED, data={"success": True}))
