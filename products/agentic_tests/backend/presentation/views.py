"""DRF views for agentic_tests."""

from typing import Any

from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.agentic_tests.backend.logic.execution import execute_agentic_test
from products.agentic_tests.backend.logic.scheduling import refresh_next_run_at
from products.agentic_tests.backend.models import AgenticTest, AgenticTestRun

from .serializers import AgenticTestRunSerializer, AgenticTestSerializer


class AgenticTestViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = AgenticTest.objects.all()
    serializer_class = AgenticTestSerializer

    def safely_get_queryset(self, queryset: QuerySet[AgenticTest]) -> QuerySet[AgenticTest]:
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        test = serializer.save(
            team_id=self.team_id,
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )
        refresh_next_run_at(test)

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        test = serializer.save()
        refresh_next_run_at(test)

    @extend_schema(
        request=None,
        responses=AgenticTestRunSerializer,
        description="Trigger an immediate run of this agentic test (mocked until browserbase wiring lands).",
    )
    @action(detail=True, methods=["post"])
    def run_now(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: AgenticTest = self.get_object()
        run = execute_agentic_test(test)
        return Response(AgenticTestRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        request=None,
        responses=AgenticTestSerializer,
        description="Mark a proposed or paused test as active.",
    )
    @action(detail=True, methods=["post"])
    def activate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: AgenticTest = self.get_object()
        test.status = AgenticTest.Status.ACTIVE
        test.save(update_fields=["status", "updated_at"])
        refresh_next_run_at(test)
        return Response(self.get_serializer(test).data)

    @extend_schema(
        request=None,
        responses=AgenticTestSerializer,
        description="Mark a test as paused.",
    )
    @action(detail=True, methods=["post"])
    def pause(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: AgenticTest = self.get_object()
        test.status = AgenticTest.Status.PAUSED
        test.next_run_at = None
        test.save(update_fields=["status", "next_run_at", "updated_at"])
        return Response(self.get_serializer(test).data)

    @extend_schema(
        request=None,
        responses=AgenticTestSerializer,
        description="Reject a proposed test. The test is kept (status=rejected) so users can restore it later.",
    )
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: AgenticTest = self.get_object()
        test.status = AgenticTest.Status.REJECTED
        test.next_run_at = None
        test.save(update_fields=["status", "next_run_at", "updated_at"])
        return Response(self.get_serializer(test).data)


class AgenticTestRunViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = AgenticTestRun.objects.all()
    serializer_class = AgenticTestRunSerializer

    def _should_skip_parents_filter(self) -> bool:
        # AgenticTestRun has no direct `team` FK — it's reachable via agentic_test.team.
        # We filter via the parent test in `safely_get_queryset` instead.
        return True

    def safely_get_queryset(self, queryset: QuerySet[AgenticTestRun]) -> QuerySet[AgenticTestRun]:
        qs = queryset.filter(agentic_test__team_id=self.team_id)
        test_id = self.request.query_params.get("agentic_test")
        if test_id:
            qs = qs.filter(agentic_test_id=test_id)
        return qs.order_by("-started_at")
