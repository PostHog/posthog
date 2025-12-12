from datetime import timedelta
from typing import Any

from django.utils import timezone

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Dashboard, EventDefinition, Experiment, FeatureFlag, Survey
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

from products.data_warehouse.backend.models import DataWarehouseTable


class FeedItemSerializer(serializers.Serializer):
    id = serializers.CharField()  # Can be int or UUID, so use CharField
    type = serializers.CharField()
    name = serializers.CharField()
    created_at = serializers.DateTimeField(required=False)
    description = serializers.CharField(required=False, allow_null=True)
    created_by = serializers.CharField(required=False, allow_null=True)
    additional_data = serializers.JSONField(required=False)


class FeedViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    @action(detail=False, methods=["GET"])
    def recent_updates(self, request, **kwargs):
        """
        Get recent updates for the feed page.
        """
        team = self.team
        days = int(request.query_params.get("days", 7))
        period_start = timezone.now() - timedelta(days=days)
        period_end = timezone.now()

        feed_items: list[dict[str, Any]] = []

        # New dashboards
        try:
            dashboards = (
                Dashboard.objects.filter(
                    team_id=team.id,
                    created_at__gt=period_start,
                    created_at__lte=period_end,
                )
                .select_related("created_by")
                .only("id", "name", "created_at", "description", "created_by__id", "created_by__email")
                .order_by("-created_at")
            )

            for dashboard in dashboards:
                feed_items.append(
                    {
                        "id": dashboard.id,
                        "type": "dashboard",
                        "name": dashboard.name,
                        "created_at": dashboard.created_at,
                        "description": dashboard.description or "New dashboard created",
                        "created_by": dashboard.created_by.email if dashboard.created_by else None,
                    }
                )
        except Exception:
            pass

        # New event definitions
        try:
            event_defs = (
                EventDefinition.objects.filter(
                    team_id=team.id,
                    created_at__gt=period_start,
                    created_at__lte=period_end,
                )
                .only("id", "name", "created_at")
                .order_by("-created_at")
            )

            for event_def in event_defs:
                feed_items.append(
                    {
                        "id": str(event_def.id),
                        "type": "event_definition",
                        "name": event_def.name,
                        "created_at": event_def.created_at,
                        "description": "New event definition",
                    }
                )
        except Exception:
            pass

        # Experiments launched
        try:
            experiments = (
                Experiment.objects.filter(
                    team_id=team.id,
                    start_date__gt=period_start,
                    start_date__lte=period_end,
                )
                .select_related("created_by")
                .only("id", "name", "start_date", "description", "created_by__id", "created_by__email")
                .order_by("-start_date")
            )

            for exp in experiments:
                feed_items.append(
                    {
                        "id": exp.id,
                        "type": "experiment_launched",
                        "name": exp.name,
                        "created_at": exp.start_date,
                        "description": exp.description or "Experiment launched",
                        "created_by": exp.created_by.email if exp.created_by else None,
                    }
                )
        except Exception:
            pass

        # New feature flags
        try:
            feature_flags = (
                FeatureFlag.objects.filter(
                    team_id=team.id,
                    created_at__gt=period_start,
                    created_at__lte=period_end,
                )
                .select_related("created_by")
                .only("id", "name", "key", "created_at", "created_by__id", "created_by__email")
                .order_by("-created_at")
            )

            for flag in feature_flags:
                feed_items.append(
                    {
                        "id": flag.id,
                        "type": "feature_flag",
                        "name": flag.name,
                        "created_at": flag.created_at,
                        "description": f"New feature flag: {flag.key}",
                        "created_by": flag.created_by.email if flag.created_by else None,
                        "additional_data": {"key": flag.key},
                    }
                )
        except Exception:
            pass

        # New surveys
        try:
            surveys = (
                Survey.objects.filter(
                    team_id=team.id,
                    start_date__gt=period_start,
                    start_date__lte=period_end,
                )
                .select_related("created_by")
                .only("id", "name", "start_date", "description", "created_by__id", "created_by__email")
                .order_by("-start_date")
            )

            for survey in surveys:
                feed_items.append(
                    {
                        "id": str(survey.id),
                        "type": "survey",
                        "name": survey.name,
                        "created_at": survey.start_date,
                        "description": survey.description or "New survey launched",
                        "created_by": survey.created_by.email if survey.created_by else None,
                    }
                )
        except Exception:
            pass

        # New replay playlists
        try:
            playlists = (
                SessionRecordingPlaylist.objects.filter(
                    team_id=team.id,
                    created_at__gt=period_start,
                    created_at__lte=period_end,
                    deleted=False,
                )
                .select_related("created_by")
                .only(
                    "short_id",
                    "name",
                    "derived_name",
                    "created_at",
                    "description",
                    "created_by__id",
                    "created_by__email",
                )
                .order_by("-created_at")
            )

            for playlist in playlists:
                feed_items.append(
                    {
                        "id": playlist.short_id,
                        "type": "session_recording_playlist",
                        "name": playlist.name or playlist.derived_name or "Untitled playlist",
                        "created_at": playlist.created_at,
                        "description": playlist.description or "New replay playlist created",
                        "created_by": playlist.created_by.email if playlist.created_by else None,
                    }
                )
        except Exception:
            pass

        # New data warehouse tables (external data sources)
        try:
            tables = (
                DataWarehouseTable.objects.filter(
                    team_id=team.id,
                    created_at__gt=period_start,
                    created_at__lte=period_end,
                    deleted=False,
                )
                .select_related("created_by")
                .only("id", "name", "created_at", "created_by__id", "created_by__email")
                .order_by("-created_at")
            )

            for table in tables:
                feed_items.append(
                    {
                        "id": str(table.id),
                        "type": "external_data_source",
                        "name": table.name,
                        "created_at": table.created_at,
                        "description": "New data source added",
                        "created_by": table.created_by.email if table.created_by else None,
                    }
                )
        except Exception:
            pass

        # Sort all items by created_at (most recent first)
        feed_items.sort(key=lambda x: x.get("created_at", period_start), reverse=True)

        serializer = FeedItemSerializer(feed_items, many=True)
        return Response({"results": serializer.data, "count": len(serializer.data)})
