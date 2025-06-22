import json
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
from posthog.models.experiment import Experiment, ExperimentGeneratedSummary
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer
from posthog.schema import HumanMessage

logger = structlog.get_logger(__name__)


class ExperimentSummaryRequestSerializer(serializers.Serializer):
    """Basic serializer for experiment summary requests"""

    prompt = serializers.CharField(
        default="Generate a simple summary of this experiment", help_text="The prompt to send to the LLM"
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

    @action(methods=["POST"], detail=True, url_path="generate_summary", required_scopes=["experiment:write"])
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
            user=cast(User, request.user), team=self.team, type=Conversation.Type.ASSISTANT
        )

        # Create a simple human message with the prompt
        human_message = HumanMessage(content=serializer.validated_data["prompt"])

        # Create the Assistant (same as MaxAI)
        assistant = Assistant(
            team=self.team,
            conversation=conversation,
            new_message=human_message,
            mode=AssistantMode.ASSISTANT,  # Use the same mode as MaxAI
            user=cast(User, request.user),
            is_new_conversation=True,
            trace_id=str(uuid4()),
        )

        # Store original method and wrap it with database save
        original_stream_method = assistant._stream

        def safe_stream_wrapper():
            """Wrapper generator that saves to database and handles errors gracefully."""
            summary = ""
            tokens_used = 0

            try:
                for chunk in original_stream_method():
                    # Parse the SSE format to extract content
                    lines = chunk.split("\n")
                    for line in lines:
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])  # Remove "data: " prefix
                                if data.get("type") == "ai" and data.get("content"):
                                    summary = data["content"]
                                    logger.debug(
                                        "Extracted content", content=data["content"], summary_length=len(summary)
                                    )
                            except json.JSONDecodeError:
                                pass

                    yield chunk

                # Save to database after streaming is complete
                logger.info("Streaming complete", summary_length=len(summary), experiment_id=experiment.id)
                if summary:
                    try:
                        # Create a basic snapshot of experiment data
                        experiment_snapshot = {
                            "id": experiment.id,
                            "name": experiment.name,
                            "description": experiment.description,
                            "type": experiment.type,
                            "start_date": experiment.start_date.isoformat() if experiment.start_date else None,
                            "end_date": experiment.end_date.isoformat() if experiment.end_date else None,
                            "conclusion": experiment.conclusion,
                            "conclusion_comment": experiment.conclusion_comment,
                            "metrics": experiment.metrics,
                            "variants": experiment.variants,
                            "stats_config": experiment.stats_config,
                            "exposure_criteria": experiment.exposure_criteria,
                        }

                        ExperimentGeneratedSummary.objects.create(
                            experiment=experiment,
                            summary=summary,
                            experiment_results_snapshot=experiment_snapshot,
                            llm_tokens_used=tokens_used,  # TODO: We need to figure out how to get the tokens used
                            llm_model="gpt-4",  # Default model? We need to figure out what model is used
                        )
                    except Exception as db_error:
                        logger.exception(
                            "Failed to save summary to database", error=str(db_error), experiment_id=experiment.id
                        )

            except Exception as e:
                logger.exception("Error in safe_stream_wrapper", error=str(e), experiment_id=experiment.id)
                yield f"data: {json.dumps({'error': 'Failed to generate summary'})}\n\n"
                yield "data: [DONE]\n\n"

        assistant._stream = safe_stream_wrapper  # type: ignore[method-assign]

        return StreamingHttpResponse(assistant.stream(), content_type=ServerSentEventRenderer.media_type)

    @action(methods=["GET"], detail=True, url_path="latest_summary", required_scopes=["experiment:read"])
    def latest_summary(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Get the latest generated summary for an experiment.
        """
        experiment = self.get_object()
        latest_summary = experiment.get_latest_generated_summary()

        if not latest_summary:
            return Response({"summary": None}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "summary": latest_summary.summary,
                "created_at": latest_summary.created_at,
                "created_by": latest_summary.created_by.id
                if latest_summary.created_by
                else None,  # TODO: we added this here but there's no created_by field in the model. needs fixing.
            }
        )
