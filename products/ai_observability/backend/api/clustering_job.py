from typing import Any

from django.db import IntegrityError, transaction

from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action

from products.cohorts.backend.models.cohort import Cohort

from ..models.clustering_job import ClusteringJob
from .metrics import llma_track_latency

MAX_JOBS_PER_TEAM = 10
_COHORT_FILTER_TYPES = ("cohort", "static-cohort", "precalculated-cohort")


class ClusteringJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClusteringJob
        fields = [
            "id",
            "name",
            "analysis_level",
            "event_filters",
            "enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate_event_filters(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reject filters that reference a cohort that doesn't exist (or is deleted).

        Saved jobs run on a schedule with no human in the loop, so a dangling
        cohort id would silently break sampling. Catching it at save time gives
        the user immediate feedback. Cohorts deleted *after* save are still
        handled defensively in the sampling activity itself.
        """
        team = self.context["get_team"]()
        referenced_ids: list[int] = []
        for f in value:
            if f.get("type") not in _COHORT_FILTER_TYPES:
                continue
            cohort_value = f.get("value")
            if not isinstance(cohort_value, (int, str)):
                continue
            try:
                referenced_ids.append(int(cohort_value))
            except (TypeError, ValueError):
                # Non-numeric cohort references (e.g. name lookups) are passed
                # through untouched — the resolver validates them at query time.
                continue

        if referenced_ids:
            existing = set(
                Cohort.objects.filter(
                    team__project_id=team.project_id,
                    id__in=referenced_ids,
                    deleted=False,
                ).values_list("id", flat=True)
            )
            missing = sorted({cid for cid in referenced_ids if cid not in existing})
            if missing:
                raise serializers.ValidationError(f"Cohort(s) not found or deleted: {missing}")

        return value


class ClusteringJobViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for clustering job configurations (max 10 per team)."""

    scope_object = "llm_analytics"
    permission_classes = [IsAuthenticated]
    serializer_class = ClusteringJobSerializer
    queryset = ClusteringJob.objects.all()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).order_by("created_at")

    @llma_track_latency("llma_clustering_job_list")
    @monitor(feature=None, endpoint="llma_clustering_job_list", method="GET")
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_clustering_job_create")
    @monitor(feature=None, endpoint="llma_clustering_job_create", method="POST")
    def create(self, request: Request, *args, **kwargs) -> Response:
        try:
            with transaction.atomic():
                existing_count = ClusteringJob.objects.filter(team_id=self.team_id).select_for_update().count()
                if existing_count >= MAX_JOBS_PER_TEAM:
                    return Response(
                        {"detail": f"Maximum of {MAX_JOBS_PER_TEAM} clustering jobs per team."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                return super().create(request, *args, **kwargs)
        except IntegrityError:
            return Response(
                {"detail": "A clustering job with this name already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def perform_create(self, serializer):
        instance = serializer.save(team_id=self.team_id)

        # Disable the migration-created default job for the same level.
        # Creating a custom job signals the default catch-all is too noisy.
        disabled_count = (
            ClusteringJob.objects.filter(
                team_id=self.team_id,
                analysis_level=instance.analysis_level,
                name__startswith="Default - ",
                enabled=True,
            )
            .exclude(id=instance.id)
            .update(enabled=False)
        )

        report_user_action(
            self.request.user,
            "llma clustering job created",
            {
                "job_id": instance.id,
                "name": instance.name,
                "analysis_level": instance.analysis_level,
                "defaults_disabled": disabled_count,
            },
            team=self.team,
        )

    @llma_track_latency("llma_clustering_job_update")
    @monitor(feature=None, endpoint="llma_clustering_job_update", method="PATCH")
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        try:
            return super().partial_update(request, *args, **kwargs)
        except IntegrityError:
            return Response(
                {"detail": "A clustering job with this name already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def perform_update(self, serializer):
        instance = serializer.save()
        report_user_action(
            self.request.user,
            "llma clustering job updated",
            {"job_id": instance.id, "name": instance.name},
            team=self.team,
        )

    @llma_track_latency("llma_clustering_job_destroy")
    @monitor(feature=None, endpoint="llma_clustering_job_destroy", method="DELETE")
    def destroy(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        report_user_action(
            self.request.user,
            "llma clustering job deleted",
            {"job_id": instance.id, "name": instance.name},
            team=self.team,
        )
        return super().destroy(request, *args, **kwargs)
