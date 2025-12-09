from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from posthog.api.mixins import validated_request

from .serializers import AIVisibilityTriggerResponseSerializer, AIVisibilityTriggerSerializer
from .temporal.client import trigger_ai_visibility_workflow

logger = structlog.get_logger(__name__)


@extend_schema(tags=["ai-visibility"])
@method_decorator(csrf_exempt, name="dispatch")
class AIVisibilityViewSet(viewsets.GenericViewSet):
    serializer_class = AIVisibilityTriggerSerializer
    http_method_names = ["post"]
    authentication_classes: list = []
    permission_classes = [AllowAny]

    @validated_request(
        request_serializer=AIVisibilityTriggerSerializer,
        responses={
            201: OpenApiResponse(
                response=AIVisibilityTriggerResponseSerializer, description="Workflow started for supplied domain"
            )
        },
        summary="Start AI visibility workflow (public)",
        description="Kick off the AI visibility Temporal workflow for a domain. Fire-and-forget; returns workflow id.",
    )
    def create(self, request, *args, **kwargs):
        domain = request.validated_data["domain"]

        workflow_id = trigger_ai_visibility_workflow(domain=domain, team_id=None, user_id=None)

        logger.info(
            "ai_visibility.triggered",
            domain=domain,
            workflow_id=workflow_id,
        )

        serializer = AIVisibilityTriggerResponseSerializer({"workflow_id": workflow_id, "status": "started"})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
