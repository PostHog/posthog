import json
from collections.abc import Generator
from typing import Any, cast
from uuid import uuid4

import structlog
from django.http import StreamingHttpResponse
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from django.db.models import QuerySet

from ee.hogai.assistant import Assistant
from ee.hogai.utils.types import AssistantMode
from ee.models.assistant import Conversation
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.experiment import Experiment, ExperimentGeneratedSummary
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer
from posthog.schema import HumanMessage

logger = structlog.get_logger(__name__)


class ExperimentSummaryRequestSerializer(serializers.Serializer):
    """Basic serializer for experiment summary requests"""
    prompt = serializers.CharField(
        default="Generate a simple summary of this experiment",
        help_text="The prompt to send to the LLM"
    )


class ExperimentSummaryViewSet(ForbidDestroyModel, TeamAndOrgViewSetMixin, GenericViewSet):
    """
    ViewSet for generating AI summaries of experiments.
    """

    scope_object = "experiment"
    queryset = Experiment.objects.all()
    renderer_classes = [SafeJSONRenderer, ServerSentEventRenderer]
    throttle_classes = [AIBurstRateThrottle, AISustainedRateThrottle]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        # Optional: Add custom filtering logic
        return queryset

    def stream_response(self, experiment: Experiment, assistant: Assistant) -> Generator[str, None, None]:
        summary = ""
        tokens_used = 0

        for chunk in assistant.stream():
            if chunk.content:
                summary += chunk.content
                yield f"data: {json.dumps({'content': chunk.content})}\n\n"

            if hasattr(chunk, "tokens_used"):
                tokens_used += chunk.tokens_used

        yield "data: [DONE]\n\n"

        ExperimentGeneratedSummary.objects.create(
            experiment=experiment,
            summary=summary,
            experiment_results_snapshot=experiment.get_results_snapshot(),
            llm_tokens_used=tokens_used
        )

    @action(
        methods=["POST"],
        detail=True,
        url_path="generate_summary",
        required_scopes=["experiment:write"]
    )
    def generate_summary(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse:
        """
        Generate an AI summary for an experiment using the same LLM as MaxAI.
        """
        # Validate request
        serializer = ExperimentSummaryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Get the experiment
        experiment = self.get_object()

        # Create a conversation (required by Assistant)
        conversation = Conversation.objects.create(
            user=cast(User, request.user),
            team=self.team,
            type=Conversation.Type.ASSISTANT
        )

        # Create a simple human message with the prompt
        human_message = HumanMessage(
            content=serializer.validated_data["prompt"]
        )

        # Create the Assistant (same as MaxAI)
        assistant = Assistant(
            team=self.team,
            conversation=conversation,
            new_message=human_message,
            mode=AssistantMode.ASSISTANT,  # Use the same mode as MaxAI
            user=cast(User, request.user),
            is_new_conversation=True,
            trace_id=str(uuid4())
        )

        # Return streaming response (same as MaxAI)
        return StreamingHttpResponse(
            assistant.stream(),
            content_type=ServerSentEventRenderer.media_type
        )

    @action(
        methods=["GET"],
        detail=True,
        url_path="latest_summary",
        required_scopes=["experiment:read"]
    )
    def latest_summary(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Get the latest generated summary for an experiment.
        """
        experiment = self.get_object()
        latest_summary = experiment.get_latest_generated_summary()

        if not latest_summary:
            return Response({"summary": None}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "summary": latest_summary.summary,
            "created_at": latest_summary.created_at,
            "created_by": latest_summary.created_by.id if latest_summary.created_by else None,
        })
