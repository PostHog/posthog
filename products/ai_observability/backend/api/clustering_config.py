from typing import cast

from django.db import transaction

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.permissions import AccessControlPermission

from ..facade.api import validate_clustering_filters
from ..logic.clustering.constants import MAX_JOBS_PER_TEAM
from ..models.clustering_config import ClusteringConfig
from ..models.clustering_job import DEFAULT_LEVEL_SPECS, ClusteringAnalysisLevel, ClusteringJob
from ..models.clustering_run import ClusteringRunStatus
from .metrics import llma_track_latency


@extend_schema_serializer(many=False)
class ClusteringConfigSerializer(serializers.ModelSerializer):
    enabled = serializers.BooleanField(help_text="Whether this project has opted in to automated clustering.")
    event_filters = serializers.ListField(
        child=serializers.DictField(child=serializers.JSONField()),
        help_text="PostHog property filters that scope automated clustering jobs. Empty array means no saved filters.",
    )

    class Meta:
        model = ClusteringConfig
        fields = [
            "enabled",
            "event_filters",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "created_at",
            "updated_at",
        ]


class ClusteringConfigSetEventFiltersSerializer(serializers.Serializer):
    event_filters = serializers.ListField(
        child=serializers.DictField(child=serializers.JSONField()),
        help_text="PostHog property filters to save for automated clustering jobs. Pass an empty array to clear filters.",
    )


class ClusteringConfigSetEnabledSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(help_text="Enable or disable automated clustering for this project.")


class ClusteringJobProgressSerializer(serializers.Serializer):
    job_id = serializers.UUIDField(help_text="The clustering job whose first run is tracked.")
    name = serializers.CharField(help_text="Job name.")
    analysis_level = serializers.ChoiceField(
        choices=ClusteringAnalysisLevel.choices, help_text="Items grouped by this job."
    )
    has_filters = serializers.BooleanField(help_text="Whether the job only includes items matching saved filters.")
    minimum = serializers.IntegerField(help_text="Minimum eligible items needed to attempt clustering.")
    lookback_days = serializers.IntegerField(help_text="Number of recent days searched for eligible items.")
    status = serializers.ChoiceField(
        choices=ClusteringRunStatus.choices,
        allow_null=True,
        help_text="First-run processing state, or null before a run has been requested.",
    )
    eligible_count = serializers.IntegerField(
        allow_null=True, help_text="Eligible items found, capped at the minimum; null while checking."
    )
    prepared_count = serializers.IntegerField(help_text="Items prepared for clustering in this run.")
    cluster_count = serializers.IntegerField(
        allow_null=True, help_text="Groups found, excluding outliers; null until finished."
    )
    failure_reason = serializers.CharField(help_text="Stable failure code, without internal error details.")
    updated_at = serializers.DateTimeField(allow_null=True, help_text="When the worker last updated this run.")
    result_run_id = serializers.CharField(help_text="The completed result to wait for in clustering queries.")


class ClusteringRetrySerializer(serializers.Serializer):
    job_id = serializers.UUIDField(help_text="Failed clustering job to retry.")


class ClusteringConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Team-level clustering configuration (event filters for automated pipelines)."""

    scope_object = "ai_observability_clusters"
    serializer_class = _FallbackSerializer
    permission_classes = [IsAuthenticated, AccessControlPermission]

    @extend_schema(request=ClusteringConfigSetEnabledSerializer, responses={200: ClusteringConfigSerializer})
    @action(detail=False, methods=["post"], required_scopes=["ai_observability_clusters:write"])
    def set_enabled(self, request: Request, **kwargs) -> Response:
        from ..facade.api import request_first_clustering_runs

        serializer = ClusteringConfigSetEnabledSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enabled = serializer.validated_data["enabled"]
        if enabled and not self.team.organization.is_ai_data_processing_approved:
            return Response(
                {"detail": "Accept AI data processing before enabling clustering."}, status=status.HTTP_400_BAD_REQUEST
            )
        with transaction.atomic():
            config, _ = ClusteringConfig.objects.get_or_create(team_id=self.team_id)
            config = ClusteringConfig.objects.select_for_update().get(team_id=self.team_id)
            config.enabled = enabled
            config.save(update_fields=["enabled", "updated_at"])
            if enabled:
                existing_levels = list(
                    ClusteringJob.objects.filter(team_id=self.team_id).values_list("analysis_level", flat=True)
                )
                ClusteringJob.objects.bulk_create(
                    [
                        ClusteringJob(
                            team_id=self.team_id,
                            name=name,
                            analysis_level=level,
                            enabled=True,
                            event_filters=config.event_filters,
                        )
                        for name, level in DEFAULT_LEVEL_SPECS
                        if level not in existing_levels
                    ][: max(0, MAX_JOBS_PER_TEAM - len(existing_levels))],
                    ignore_conflicts=True,
                )
                request_first_clustering_runs(self.team_id, cast(User, request.user))
        report_user_action(
            request.user,
            "llma clustering enabled changed",
            {"enabled": enabled},
            team=self.team,
            request=request,
        )
        return Response(ClusteringConfigSerializer(config).data)

    @extend_schema(responses={200: ClusteringJobProgressSerializer(many=True)})
    @action(detail=False, methods=["get"], required_scopes=["ai_observability_clusters:read"])
    def progress(self, request: Request, **kwargs) -> Response:
        from ..facade.api import clustering_job_progress

        return Response(
            ClusteringJobProgressSerializer(
                clustering_job_progress(self.team_id, cast(User, request.user)), many=True
            ).data
        )

    @extend_schema(request=ClusteringRetrySerializer, responses={200: ClusteringJobProgressSerializer(many=True)})
    @action(detail=False, methods=["post"], required_scopes=["ai_observability_clusters:write"])
    def retry(self, request: Request, **kwargs) -> Response:
        from ..facade.api import clustering_job_progress, request_first_clustering_runs

        serializer = ClusteringRetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not self.team.organization.is_ai_data_processing_approved:
            return Response(
                {"detail": "Accept AI data processing before retrying clustering."}, status=status.HTTP_400_BAD_REQUEST
            )
        request_first_clustering_runs(self.team_id, cast(User, request.user), serializer.validated_data["job_id"])
        report_user_action(
            request.user,
            "llma clustering first run retried",
            {"job_id": str(serializer.validated_data["job_id"])},
            team=self.team,
            request=request,
        )
        return Response(
            ClusteringJobProgressSerializer(
                clustering_job_progress(self.team_id, cast(User, request.user)), many=True
            ).data
        )

    @extend_schema(responses={200: ClusteringConfigSerializer})
    @llma_track_latency("llma_clustering_config_list")
    @monitor(feature=None, endpoint="llma_clustering_config_list", method="GET")
    def list(self, request: Request, **kwargs) -> Response:
        config, _ = ClusteringConfig.objects.get_or_create(team_id=self.team_id)
        serializer = ClusteringConfigSerializer(config)
        return Response(serializer.data)

    @extend_schema(request=ClusteringConfigSetEventFiltersSerializer, responses={200: ClusteringConfigSerializer})
    @action(detail=False, methods=["post"], required_scopes=["ai_observability_clusters:write"])
    @llma_track_latency("llma_clustering_config_set_event_filters")
    @monitor(feature=None, endpoint="llma_clustering_config_set_event_filters", method="POST")
    def set_event_filters(self, request: Request, **kwargs) -> Response:
        event_filters = request.data.get("event_filters")

        if event_filters is None:
            return Response(
                {"detail": "event_filters is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(event_filters, list):
            return Response(
                {"detail": "event_filters must be a list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        validate_clustering_filters(self.team_id, cast(User, request.user), event_filters)
        config, _ = ClusteringConfig.objects.get_or_create(team_id=self.team_id)
        config.event_filters = event_filters
        config.save(update_fields=["event_filters", "updated_at"])

        report_user_action(
            request.user,
            "llma clustering config event filters set",
            {
                "filter_count": len(event_filters),
            },
            team=self.team,
            request=self.request,
        )

        serializer = ClusteringConfigSerializer(config)
        return Response(serializer.data)
