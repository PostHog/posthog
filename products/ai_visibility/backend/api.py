import json

from django.db import models
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
        force = request.validated_data.get("force", False)
        run_id = request.validated_data.get("run_id")

        # If polling for a specific run, check its status
        if run_id:
            try:
                specific_run = AiVisibilityRun.objects.get(id=run_id)
                if specific_run.status == AiVisibilityRun.Status.READY and specific_run.s3_path:
                    results_json = object_storage.read(specific_run.s3_path)
                    if results_json:
                        results = json.loads(results_json)
                        serializer = AIVisibilityResultResponseSerializer(
                            {
                                "status": "ready",
                                "run_id": specific_run.id,
                                "domain": domain,
                                "results": results,
                            }
                        )
                        return Response(serializer.data, status=status.HTTP_200_OK)
                elif specific_run.status == AiVisibilityRun.Status.RUNNING:
                    serializer = AIVisibilityStartedResponseSerializer(
                        {
                            "workflow_id": specific_run.workflow_id,
                            "run_id": specific_run.id,
                            "status": "running",
                            "created_at": specific_run.created_at,
                        }
                    )
                    return Response(serializer.data, status=status.HTTP_200_OK)
                # If FAILED, fall through to create a new run
            except AiVisibilityRun.DoesNotExist:
                pass

        existing_run = None
        if not force:
            # Check for existing run (prefer READY over RUNNING)
            existing_run = (
                AiVisibilityRun.objects.filter(
                    domain=domain,
                    status__in=[AiVisibilityRun.Status.READY, AiVisibilityRun.Status.RUNNING],
                )
                .order_by(
                    # READY first, then RUNNING
                    models.Case(
                        models.When(status=AiVisibilityRun.Status.READY, then=0),
                        models.When(status=AiVisibilityRun.Status.RUNNING, then=1),
                        default=2,
                    )
                )
                .first()
            )

        if existing_run:
            if existing_run.status == AiVisibilityRun.Status.READY and existing_run.s3_path:
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
            elif existing_run.status == AiVisibilityRun.Status.RUNNING:
                serializer = AIVisibilityStartedResponseSerializer(
                    {
                        "workflow_id": existing_run.workflow_id,
                        "run_id": existing_run.id,
                        "status": "running",
                        "created_at": existing_run.created_at,
                    }
                )
                return Response(serializer.data, status=status.HTTP_200_OK)

        # No existing run (or only failed runs), create a new one
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

        serializer = AIVisibilityStartedResponseSerializer(
            {"workflow_id": workflow_id, "run_id": run.id, "status": "started", "created_at": run.created_at}
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
