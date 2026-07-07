"""API endpoints for evaluation report configuration and report run history."""

import datetime as dt
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.integration import Integration
from posthog.permissions import AccessControlPermission

from products.ai_observability.backend.api.metrics import llma_track_latency
from products.ai_observability.backend.models.evaluation_configs import (
    REPORTABLE_OUTPUT_TYPES,
    evaluation_supports_reports,
)
from products.ai_observability.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun
from products.ai_observability.backend.models.evaluations import EvaluationTarget
from products.workflows.backend.utils.rrule_utils import validate_rrule

logger = structlog.get_logger(__name__)

SCHEDULE_RRULE_ERROR = (
    "Scheduled reports support daily or weekly cadences. Use 'FREQ=DAILY' or 'FREQ=WEEKLY;BYDAY=MO,FR'."
)
VALID_WEEKDAYS = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}


def validate_report_schedule_rrule(rrule_string: str) -> None:
    parts: dict[str, str] = {}
    for part in rrule_string.split(";"):
        if "=" not in part:
            raise ValueError(SCHEDULE_RRULE_ERROR)
        key, value = part.split("=", 1)
        if key in parts:
            raise ValueError(SCHEDULE_RRULE_ERROR)
        parts[key] = value

    if parts == {"FREQ": "DAILY"}:
        return

    if set(parts) == {"FREQ", "BYDAY"} and parts["FREQ"] == "WEEKLY":
        weekdays = parts["BYDAY"].split(",")
        if weekdays and all(day in VALID_WEEKDAYS for day in weekdays) and len(weekdays) == len(set(weekdays)):
            return

    raise ValueError(SCHEDULE_RRULE_ERROR)


class EvaluationReportSerializer(serializers.ModelSerializer):
    created_instance = True

    class Meta:
        model = EvaluationReport
        fields = [
            "id",
            "evaluation",
            "frequency",
            "rrule",
            "starts_at",
            "timezone_name",
            "next_delivery_date",
            "delivery_targets",
            "max_sample_size",
            "enabled",
            "deleted",
            "last_delivered_at",
            "report_prompt_guidance",
            "trigger_threshold",
            "cooldown_minutes",
            "daily_run_cap",
            "created_by",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "starts_at",
            "timezone_name",
            "next_delivery_date",
            "deleted",
            "last_delivered_at",
            "created_by",
            "created_at",
        ]
        extra_kwargs = {
            "evaluation": {"help_text": "UUID of the evaluation this report config belongs to."},
            "frequency": {
                "help_text": (
                    "How report generation is triggered. 'every_n' fires once N new evaluation results have "
                    "accumulated (subject to cooldown_minutes and daily_run_cap). 'scheduled' fires on the cadence "
                    "defined by rrule."
                )
            },
            "rrule": {
                "help_text": (
                    "RFC 5545 recurrence rule string for scheduled reports. Only daily and weekly cadences are "
                    "supported: use 'FREQ=DAILY' or 'FREQ=WEEKLY;BYDAY=MO,FR'. Required when frequency is "
                    "'scheduled'; ignored otherwise."
                )
            },
            "starts_at": {
                "help_text": (
                    "Read-only anchor datetime used to expand scheduled reports. The server sets this automatically "
                    "when a report is switched to scheduled mode."
                )
            },
            "timezone_name": {
                "help_text": "Read-only timezone used for scheduled reports. Evaluation reports use UTC."
            },
            "delivery_targets": {
                "help_text": (
                    "List of delivery targets. Each entry is either {type: 'email', value: 'user@example.com'} or "
                    "{type: 'slack', integration_id: <int>, channel: '<channel>'}. Slack integration_id must "
                    "belong to this team."
                )
            },
            "max_sample_size": {
                "help_text": "Maximum number of evaluation runs included in each report. Defaults to 200."
            },
            "enabled": {"help_text": "Whether report delivery is active. Disabled configs do not fire."},
            "deleted": {
                "help_text": (
                    "Read-only. Report configs are soft-deleted only when their evaluation is deleted. Use "
                    "enabled=false to stop deliveries."
                )
            },
            "report_prompt_guidance": {
                "help_text": (
                    "Optional custom instructions appended to the AI report prompt to steer focus, scope, or "
                    "section choices without modifying the base prompt."
                )
            },
            "trigger_threshold": {
                "min_value": EvaluationReport.TRIGGER_THRESHOLD_MIN,
                "max_value": EvaluationReport.TRIGGER_THRESHOLD_MAX,
                "help_text": (
                    f"Number of new evaluation results that triggers a report (every_n mode only). "
                    f"Min {EvaluationReport.TRIGGER_THRESHOLD_MIN}, max {EvaluationReport.TRIGGER_THRESHOLD_MAX}. "
                    f"Defaults to {EvaluationReport.TRIGGER_THRESHOLD_DEFAULT}. Required when frequency is 'every_n'."
                ),
            },
            "cooldown_minutes": {
                "min_value": EvaluationReport.COOLDOWN_MINUTES_MIN,
                "max_value": EvaluationReport.COOLDOWN_MINUTES_MAX,
                "help_text": (
                    f"Minimum minutes between count-triggered reports to prevent spam (every_n mode only). "
                    f"Min {EvaluationReport.COOLDOWN_MINUTES_MIN}, max {EvaluationReport.COOLDOWN_MINUTES_MAX} "
                    f"(24 hours). Defaults to {EvaluationReport.COOLDOWN_MINUTES_DEFAULT}."
                ),
            },
            "daily_run_cap": {
                "min_value": EvaluationReport.DAILY_RUN_CAP_MIN,
                "max_value": EvaluationReport.DAILY_RUN_CAP_MAX,
                "help_text": (
                    f"Maximum count-triggered report runs per calendar day (UTC). "
                    f"Min {EvaluationReport.DAILY_RUN_CAP_MIN}, max {EvaluationReport.DAILY_RUN_CAP_MAX} "
                    f"(one per cooldown window). Defaults to {EvaluationReport.DAILY_RUN_CAP_DEFAULT}."
                ),
            },
        }

    def validate_evaluation(self, value):
        # Prevent creating a report in team A that references team B's evaluation:
        # the FK queryset is unscoped, so a user with access to multiple teams could
        # otherwise cross tenant boundaries by passing a foreign evaluation id.
        team = self.context["get_team"]()
        if value.team_id != team.id:
            raise serializers.ValidationError("Evaluation does not belong to this team.")
        if not evaluation_supports_reports(value.output_type):
            raise serializers.ValidationError("Reports are only supported for boolean evaluations.")
        if value.target == EvaluationTarget.TRACE:
            raise serializers.ValidationError("Reports are not yet supported for trace-level evaluations.")
        return value

    def validate_rrule(self, value: str) -> str:
        # Allow empty for count-triggered reports; cross-field validation enforces required-when-scheduled.
        if not value:
            return value
        try:
            validate_report_schedule_rrule(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        try:
            validate_rrule(value)
        except ValueError as exc:
            logger.warning("Invalid rrule provided for evaluation report", exc_info=True)
            raise serializers.ValidationError("Invalid recurrence rule.") from exc
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if isinstance(self.initial_data, dict) and "deleted" in self.initial_data:
            raise serializers.ValidationError(
                {
                    "deleted": (
                        "Report configs are deleted only when their evaluation is deleted. "
                        "Disable delivery with enabled=false."
                    )
                }
            )
        # Numeric bounds for trigger_threshold / cooldown_minutes / daily_run_cap are enforced
        # by the field-level min_value / max_value validators. This block only handles the
        # cross-field "required" rules that the field validators can't express on their own.
        frequency = attrs.get("frequency") or (
            self.instance.frequency if self.instance else EvaluationReport.Frequency.EVERY_N
        )
        if frequency == EvaluationReport.Frequency.EVERY_N:
            threshold = (
                attrs.get("trigger_threshold")
                if "trigger_threshold" in attrs
                else (self.instance.trigger_threshold if self.instance else None)
            )
            if threshold is None:
                raise serializers.ValidationError({"trigger_threshold": "Required when frequency is 'every_n'."})
        elif frequency == EvaluationReport.Frequency.SCHEDULED:
            rrule_str = attrs.get("rrule") if "rrule" in attrs else (self.instance.rrule if self.instance else "")
            if not rrule_str:
                raise serializers.ValidationError({"rrule": "Required when frequency is 'scheduled'."})
            if not self.instance or self.instance.starts_at is None:
                attrs["starts_at"] = timezone.now()
            attrs["timezone_name"] = "UTC"
        return attrs

    def validate_delivery_targets(self, value: list) -> list:
        if not isinstance(value, list):
            raise serializers.ValidationError("Delivery targets must be a list.")
        team = self.context["get_team"]()
        slack_ids_to_verify: set[int] = set()
        for target in value:
            if not isinstance(target, dict):
                raise serializers.ValidationError("Each delivery target must be an object.")
            target_type = target.get("type")
            if target_type not in ("email", "slack"):
                raise serializers.ValidationError(f"Invalid delivery target type: {target_type}")
            if target_type == "email" and not target.get("value"):
                raise serializers.ValidationError("Email delivery target must include a 'value' field.")
            if target_type == "slack":
                integration_id = target.get("integration_id")
                channel = target.get("channel")
                if not integration_id or not channel:
                    raise serializers.ValidationError(
                        "Slack delivery target must include 'integration_id' and 'channel'."
                    )
                try:
                    slack_ids_to_verify.add(int(integration_id))
                except (TypeError, ValueError):
                    raise serializers.ValidationError("Slack integration_id must be an integer.")
        if slack_ids_to_verify:
            # Enforce tenant + kind boundary: only integrations that belong to this team AND
            # are Slack integrations are valid. Prevents cross-team reuse of integration ids
            # and rejects non-Slack kinds that happen to share an id.
            owned = set(
                Integration.objects.filter(
                    team_id=team.id, kind=Integration.IntegrationKind.SLACK, id__in=slack_ids_to_verify
                ).values_list("id", flat=True)
            )
            missing = slack_ids_to_verify - owned
            if missing:
                raise serializers.ValidationError(f"Slack integration(s) not found for this team: {sorted(missing)}.")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        team = self.context["get_team"]()
        evaluation = validated_data["evaluation"]
        defaults = {**validated_data, "team": team, "created_by": request.user}
        report, created = EvaluationReport.objects.get_or_create(evaluation=evaluation, defaults=defaults)
        self.created_instance = created
        if created:
            return report

        for field, value in validated_data.items():
            if field != "evaluation":
                setattr(report, field, value)
        if report.created_by_id is None:
            report.created_by = request.user
        report.save()
        return report


class EvaluationReportListSerializer(EvaluationReportSerializer):
    """Slim list serializer for MCP callers — drops heavy per-item fields to save tokens.

    Gated on the ``X-PostHog-Client: mcp`` header so the web UI keeps the full shape
    it relies on for draft seeding and schedule editing (see
    `EvaluationReportViewSet.get_serializer_class`).
    """

    class Meta(EvaluationReportSerializer.Meta):
        fields = [
            f
            for f in EvaluationReportSerializer.Meta.fields
            if f
            not in (
                "rrule",
                "starts_at",
                "timezone_name",
                "delivery_targets",
                "max_sample_size",
                "deleted",
                "report_prompt_guidance",
                "cooldown_minutes",
                "daily_run_cap",
                "created_by",
            )
        ]
        read_only_fields = [f for f in EvaluationReportSerializer.Meta.read_only_fields if f != "created_by"]


class EvaluationReportRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationReportRun
        fields = [
            "id",
            "report",
            "content",
            "metadata",
            "period_start",
            "period_end",
            "delivery_status",
            "delivery_errors",
            "created_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "UUID of this report run."},
            "report": {"help_text": "UUID of the report config that generated this run."},
            "content": {"help_text": "Generated report content (markdown or structured text)."},
            "metadata": {"help_text": "Run metadata including model used, token counts, and generation stats."},
            "period_start": {"help_text": "Start of the evaluation window covered by this report."},
            "period_end": {"help_text": "End of the evaluation window covered by this report."},
            "delivery_status": {"help_text": "'pending', 'delivered', or 'failed'."},
            "delivery_errors": {"help_text": "List of delivery error messages if delivery failed."},
        }


class EvaluationReportViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    """CRUD for evaluation report configurations + report run history."""

    scope_object = "llm_analytics"
    permission_classes = [AccessControlPermission]
    serializer_class = EvaluationReportSerializer
    queryset = EvaluationReport.objects.all()

    @staticmethod
    def _is_mcp_request(request: Request) -> bool:
        return request.META.get("HTTP_X_POSTHOG_CLIENT") == "mcp"

    def get_serializer_class(self):
        if self.action == "list" and self._is_mcp_request(self.request):
            return EvaluationReportListSerializer
        return super().get_serializer_class()

    def safely_get_queryset(self, queryset: QuerySet[EvaluationReport]) -> QuerySet[EvaluationReport]:
        queryset = queryset.filter(team_id=self.team_id, evaluation__output_type__in=REPORTABLE_OUTPUT_TYPES).order_by(
            "-created_at"
        )
        if self.action not in ("update", "partial_update"):
            queryset = queryset.filter(deleted=False)

        evaluation_id = self.request.query_params.get("evaluation")
        if evaluation_id:
            queryset = queryset.filter(evaluation_id=evaluation_id)

        return queryset

    @llma_track_latency("llma_evaluation_reports_list")
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_evaluation_reports_create")
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        status_code = status.HTTP_201_CREATED if getattr(serializer, "created_instance", True) else status.HTTP_200_OK
        return Response(serializer.data, status=status_code, headers=headers)

    @llma_track_latency("llma_evaluation_reports_retrieve")
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        return super().retrieve(request, *args, **kwargs)

    @llma_track_latency("llma_evaluation_reports_update")
    def update(self, request: Request, *args, **kwargs) -> Response:
        return super().update(request, *args, **kwargs)

    @llma_track_latency("llma_evaluation_reports_partial_update")
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(
        responses={405: None},
        description=(
            "Evaluation report configs are deleted only when their evaluation is deleted. "
            "Use PATCH enabled=false to stop delivery."
        ),
    )
    def destroy(self, request: Request, *args, **kwargs) -> Response:
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        instance = serializer.save()
        was_created = serializer.created_instance
        report_user_action(
            self.request.user,
            "llma evaluation report created" if was_created else "llma evaluation report updated",
            {
                "evaluation_report_id": str(instance.id),
                "evaluation_id": str(instance.evaluation_id),
                "frequency": instance.frequency,
                "has_rrule": bool(instance.rrule),
                "timezone_name": instance.timezone_name,
                "delivery_target_count": len(instance.delivery_targets or []),
                "delivery_target_types": sorted(
                    {t.get("type") for t in (instance.delivery_targets or []) if t.get("type")}
                ),
                "trigger_threshold": instance.trigger_threshold,
                "enabled": instance.enabled,
                "has_prompt_guidance": bool(instance.report_prompt_guidance),
            },
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer):
        tracked_fields = [
            "frequency",
            "rrule",
            "starts_at",
            "timezone_name",
            "delivery_targets",
            "max_sample_size",
            "enabled",
            "report_prompt_guidance",
            "trigger_threshold",
            "cooldown_minutes",
            "daily_run_cap",
        ]

        changed_fields: list[str] = []
        for field in tracked_fields:
            if (
                field in serializer.validated_data
                and getattr(serializer.instance, field) != serializer.validated_data[field]
            ):
                changed_fields.append(field)

        instance = serializer.save()

        if changed_fields:
            event_properties: dict[str, Any] = {
                "evaluation_report_id": str(instance.id),
                "evaluation_id": str(instance.evaluation_id),
                "changed_fields": changed_fields,
            }
            if "enabled" in changed_fields:
                event_properties["enabled_new_value"] = instance.enabled
            report_user_action(
                self.request.user,
                "llma evaluation report updated",
                event_properties,
                team=self.team,
                request=self.request,
            )

    @extend_schema(responses=EvaluationReportRunSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="runs", required_scopes=["llm_analytics:read"])
    @llma_track_latency("llma_evaluation_report_runs_list")
    def runs(self, request: Request, **kwargs) -> Response:
        """List report runs (history) for this report."""
        report = self.get_object()
        queryset = EvaluationReportRun.objects.filter(report=report).order_by("-created_at")
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = EvaluationReportRunSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = EvaluationReportRunSerializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(request=None, responses={202: None})
    @action(detail=True, methods=["post"], url_path="generate", required_scopes=["llm_analytics:write"])
    @llma_track_latency("llma_evaluation_report_generate")
    def generate(self, request: Request, **kwargs) -> Response:
        """Trigger immediate report generation."""
        report = self.get_object()
        if not evaluation_supports_reports(report.evaluation.output_type):
            return Response(
                {"error": "Reports are only supported for boolean evaluations."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if report.evaluation.target == EvaluationTarget.TRACE:
            return Response(
                {"error": "Reports are not yet supported for trace-level evaluations."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from posthog.temporal.ai_observability.eval_reports.constants import GENERATE_EVAL_REPORT_WORKFLOW_NAME
            from posthog.temporal.ai_observability.eval_reports.types import GenerateAndDeliverEvalReportWorkflowInput
            from posthog.temporal.common.client import sync_connect
        except ImportError:
            # The eval_reports Temporal module ships in a later PR in this stack; if we're on a
            # build where it hasn't landed yet, surface a 503 instead of a confusing 500.
            logger.exception("eval_reports Temporal module not available", report_id=str(report.id))
            return Response(
                {"error": "Report generation is not yet available on this deployment."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Stable workflow ID windowed to the minute: if a user smashes the button, Temporal
        # rejects the duplicate start (WorkflowAlreadyStarted) and we treat that as success.
        workflow_id = f"eval-report-manual-{report.id}-{dt.datetime.now(tz=dt.UTC).strftime('%Y%m%dT%H%M')}"
        try:
            client = sync_connect()
            # mypy can't resolve Temporal's start_workflow overloads for string-named workflows.
            async_to_sync(client.start_workflow)(  # type: ignore[misc]
                GENERATE_EVAL_REPORT_WORKFLOW_NAME,  # type: ignore[arg-type]
                GenerateAndDeliverEvalReportWorkflowInput(report_id=str(report.id), manual=True),  # type: ignore[arg-type]
                id=workflow_id,
                task_queue=settings.LLMA_TASK_QUEUE,
            )
        except Exception as exc:
            # Temporal's WorkflowAlreadyStarted is a subclass of RPCError / Exception depending
            # on SDK version; match by name to stay version-tolerant.
            if type(exc).__name__ == "WorkflowAlreadyStartedError":
                logger.info(
                    "Duplicate evaluation report generation request coalesced",
                    report_id=str(report.id),
                    workflow_id=workflow_id,
                )
                return Response(status=status.HTTP_202_ACCEPTED)
            logger.exception("Failed to trigger evaluation report generation", report_id=str(report.id))
            return Response(
                {"error": "Failed to trigger report generation"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(status=status.HTTP_202_ACCEPTED)
