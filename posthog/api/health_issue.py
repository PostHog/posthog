from django.db.models import Case, Count, QuerySet, When

from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.health_issue import HealthIssue


class HealthIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = HealthIssue
        fields = [
            "id",
            "kind",
            "severity",
            "status",
            "dismissed",
            "payload",
            "created_at",
            "updated_at",
            "resolved_at",
        ]
        read_only_fields = [f for f in fields if f != "dismissed"]


class HealthIssuePagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 250


SEVERITY_ORDERING = Case(
    When(severity=HealthIssue.Severity.CRITICAL, then=0),
    When(severity=HealthIssue.Severity.WARNING, then=1),
    When(severity=HealthIssue.Severity.INFO, then=2),
)

VALID_STATUSES = {choice.value for choice in HealthIssue.Status}
VALID_SEVERITIES = {choice.value for choice in HealthIssue.Severity}


class HealthIssueViewSet(TeamAndOrgViewSetMixin, ListModelMixin, RetrieveModelMixin, GenericViewSet):
    scope_object = "health_issue"
    queryset = HealthIssue.objects.all()
    serializer_class = HealthIssueSerializer
    pagination_class = HealthIssuePagination
    http_method_names = ["get", "patch", "post", "head"]

    WRITABLE_FIELDS = {"dismissed"}

    def partial_update(self, request: Request, **kwargs) -> Response:
        unknown_fields = set(request.data.keys()) - self.WRITABLE_FIELDS
        if unknown_fields:
            raise serializers.ValidationError(dict.fromkeys(unknown_fields, "This field is read-only."))

        issue = self.get_object()
        serializer = self.get_serializer(issue, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = (
            queryset.filter(team_id=self.team_id)
            .annotate(severity_order=SEVERITY_ORDERING)
            .order_by("severity_order", "-created_at")
        )

        if status_filter := self.request.query_params.get("status"):
            if status_filter not in VALID_STATUSES:
                raise serializers.ValidationError({"status": f"Invalid status: {status_filter}"})
            queryset = queryset.filter(status=status_filter)

        if severity_filter := self.request.query_params.get("severity"):
            if severity_filter not in VALID_SEVERITIES:
                raise serializers.ValidationError({"severity": f"Invalid severity: {severity_filter}"})
            queryset = queryset.filter(severity=severity_filter)

        if kind_filter := self.request.query_params.get("kind"):
            queryset = queryset.filter(kind=kind_filter)

        dismissed_filter = self.request.query_params.get("dismissed")
        if dismissed_filter is not None:
            queryset = queryset.filter(dismissed=dismissed_filter.lower() == "true")

        return queryset

    @action(methods=["POST"], detail=True)
    def resolve(self, request: Request, **kwargs) -> Response:
        issue = self.get_object()
        try:
            issue.resolve()
        except ValueError:
            return Response({"detail": "Could not resolve health issue."}, status=HTTP_400_BAD_REQUEST)
        return Response(HealthIssueSerializer(issue).data)

    @action(methods=["GET"], detail=False)
    def summary(self, request: Request, **kwargs) -> Response:
        active_issues = self.get_queryset().filter(status=HealthIssue.Status.ACTIVE, dismissed=False)

        by_severity = {
            row["severity"]: row["count"]
            for row in active_issues.order_by().values("severity").annotate(count=Count("id"))
        }

        by_kind = {
            row["kind"]: row["count"] for row in active_issues.order_by().values("kind").annotate(count=Count("id"))
        }

        return Response(
            {
                "total": sum(by_severity.values()),
                "by_severity": by_severity,
                "by_kind": by_kind,
            }
        )
