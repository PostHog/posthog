import asyncio
import logging

from django.conf import settings
from django.db.models import QuerySet

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import RetryPolicy

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.temporal.common.client import sync_connect

from .models import BrowserLabTest, BrowserLabTestRun

logger = logging.getLogger(__name__)


class BrowserLabTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrowserLabTest
        fields = [
            "id",
            "name",
            "url",
            "steps",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def create(self, validated_data: dict) -> BrowserLabTest:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class BrowserLabTestRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrowserLabTestRun
        fields = [
            "id",
            "browser_lab_test",
            "status",
            "created_at",
            "finished_at",
            "result",
            "error",
        ]
        read_only_fields = fields


class BrowserLabTestViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "browser_lab_test"
    queryset = BrowserLabTest.objects.all()
    serializer_class = BrowserLabTestSerializer
    permission_classes = [IsAuthenticated]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id, deleted=False).order_by("-created_at")

    @action(detail=True, methods=["post"])
    def run(self, request: Request, *args, **kwargs) -> Response:
        browser_lab_test = self.get_object()
        browser_lab_test_run = BrowserLabTestRun.objects.create(
            browser_lab_test=browser_lab_test,
            status=BrowserLabTestRun.Status.PENDING,
        )

        from .temporal.run_browser_lab_test.workflow import RunBrowserLabTestWorkflowInput

        workflow_id = f"run-browser-lab-test-{browser_lab_test.id}-{browser_lab_test_run.id}"
        workflow_input = RunBrowserLabTestWorkflowInput(
            team_id=self.team_id,
            browser_lab_test_id=str(browser_lab_test.id),
            browser_lab_test_run_id=str(browser_lab_test_run.id),
        )

        try:
            client = sync_connect()
            asyncio.run(
                client.start_workflow(
                    "run-browser-lab-test",
                    workflow_input,
                    id=workflow_id,
                    task_queue=settings.BROWSER_LAB_TESTING_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            )
        except Exception:
            logger.exception(
                "Failed to start browser lab test workflow for browser_lab_test_id=%s", browser_lab_test.id
            )
            browser_lab_test_run.status = BrowserLabTestRun.Status.FAILED
            browser_lab_test_run.error = "Failed to start workflow"
            browser_lab_test_run.save(update_fields=["status", "error"])

        return Response(BrowserLabTestRunSerializer(browser_lab_test_run).data, status=status.HTTP_201_CREATED)


class BrowserLabTestRunViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "browser_lab_test"
    queryset = BrowserLabTestRun.objects.all()
    serializer_class = BrowserLabTestRunSerializer
    permission_classes = [IsAuthenticated]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(
            browser_lab_test_id=self.kwargs["parent_lookup_browser_lab_test_id"],
            browser_lab_test__team_id=self.team_id,
        ).order_by("-created_at")
