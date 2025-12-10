import json

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.storage import object_storage

from .models import AiVisibilityRun
from .serializers import (
    AIVisibilityResultResponseSerializer,
    AIVisibilityStartedResponseSerializer,
    AIVisibilityTriggerSerializer,
)
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
            200: OpenApiResponse(
                response=AIVisibilityResultResponseSerializer, description="Completed results for domain"
            ),
            201: OpenApiResponse(
                response=AIVisibilityStartedResponseSerializer, description="Workflow started for supplied domain"
            ),
        },
        summary="Get or start AI visibility workflow (public)",
        description="Returns completed results if available, otherwise starts a new workflow.",
    )
    def create(self, request, *args, **kwargs):
        domain = request.validated_data["domain"]

        existing_run = AiVisibilityRun.objects.filter(domain=domain, status=AiVisibilityRun.Status.READY).first()

        if existing_run and existing_run.s3_path:
            results_json = object_storage.read(existing_run.s3_path)
            if results_json:
                results = json.loads(results_json)
                serializer = AIVisibilityResultResponseSerializer(
                    {
                        "status": "ready",
                        "run_id": existing_run.id,
                        "domain": domain,
                        "results": results,
                    }
                )
                return Response(serializer.data, status=status.HTTP_200_OK)

        run = AiVisibilityRun.objects.create(
            domain=domain,
            workflow_id="",
            status=AiVisibilityRun.Status.RUNNING,
        )

        workflow_id = trigger_ai_visibility_workflow(domain=domain, run_id=str(run.id), team_id=None, user_id=None)

        run.workflow_id = workflow_id
        run.save(update_fields=["workflow_id"])

        logger.info(
            "ai_visibility.triggered",
            domain=domain,
            workflow_id=workflow_id,
            run_id=str(run.id),
        )

        serializer = AIVisibilityStartedResponseSerializer({"workflow_id": workflow_id, "status": "started"})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
