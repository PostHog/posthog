import datetime as dt

from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated, ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import (
    BatchExport,
    BatchExportDestination,
    BatchExportRun,
    Team,
    User,
)
from posthog.batch_exports.service import (
    backfill_export,
    create_batch_export,
    delete_schedule,
    pause_batch_export,
    unpause_batch_export,
)
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)
from posthog.temporal.client import sync_connect


class BatchExportRunSerializer(serializers.ModelSerializer):
    """Serializer for a BatchExportRun model."""

    class Meta:
        model = BatchExportRun
        fields = "__all__"
        read_only_fields = ["batch_export"]


class BatchExportDestinationSerializer(serializers.ModelSerializer):
    """Serializer for an BatchExportDestination model."""

    class Meta:
        model = BatchExportDestination
        fields = ["type", "config"]

    def create(self, validated_data: dict) -> BatchExportDestination:
        """Create a BatchExportDestination."""
        team = Team.objects.get(id=self.context["team_id"])
        export_destination = BatchExportDestination.objects.create(team=team, **validated_data)
        return export_destination

    def to_representation(self, instance: BatchExportDestination) -> dict:
        data = super().to_representation(instance)
        data["config"] = {
            k: v for k, v in data["config"].items() if k not in BatchExportDestination.secret_fields[instance.type]
        }
        return data


class BatchExportSerializer(serializers.ModelSerializer):
    """Serializer for a BatchExport model."""

    destination = BatchExportDestinationSerializer()

    class Meta:
        model = BatchExport
        fields = [
            "id",
            "name",
            "destination",
            "interval",
            "paused",
            "created_at",
            "last_updated_at",
        ]
        read_only_fields = [
            "id",
            "paused",
            "created_at",
            "last_updated_at",
        ]

    def create(self, validated_data: dict) -> BatchExport:
        """Create a BatchExport."""
        destination_data = validated_data.pop("destination")
        team_id = self.context["team_id"]
        interval = validated_data.pop("interval")
        name = validated_data.pop("name")

        return create_batch_export(team_id=team_id, interval=interval, name=name, destination_data=destination_data)

    def update(self, instance: BatchExport, validated_data: dict) -> BatchExport:
        """Update a BatchExport."""
        destination_data = validated_data.pop("destination", None)

        if destination_data:
            instance.destination.type = destination_data.get("type", instance.destination.type)
            instance.destination.config = {**instance.destination.config, **destination_data.get("config", {})}
            instance.destination.save()

        instance.name = validated_data.get("name", instance.name)
        instance.interval = validated_data.get("interval", instance.interval)
        instance.save()

        return instance


class BatchExportViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = BatchExport.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    serializer_class = BatchExportSerializer

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        return self.queryset.filter(team_id=self.team_id).exclude(deleted=True).prefetch_related("destination")

    @action(methods=["POST"], detail=True)
    def backfill(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Trigger a backfill for a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        start_at_input = request.data.get("start_at", None)
        end_at_input = request.data.get("end_at", None)

        start_at = dt.datetime.fromisoformat(start_at_input) if start_at_input is not None else None
        end_at = dt.datetime.fromisoformat(end_at_input) if end_at_input is not None else None

        batch_export = self.get_object()
        run = backfill_export(batch_export.pk, start_at, end_at)

        serializer = BatchExportRunSerializer(run)
        return response.Response(serializer.data)

    @action(methods=["POST"], detail=True)
    def pause(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Pause a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id
        note = f"Unpause requested by user {user_id} from team {team_id}"

        batch_export = self.get_object()
        temporal = sync_connect()
        try:
            pause_batch_export(temporal, str(batch_export.id), note=note)
        except ValueError:
            raise ValidationError("Cannot pause a BatchExport that is already paused")

        return response.Response({"paused": True})

    @action(methods=["POST"], detail=True)
    def unpause(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Unpause a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id
        note = f"Unpause requested by user {user_id} from team {team_id}"

        batch_export = self.get_object()
        temporal = sync_connect()
        try:
            unpause_batch_export(temporal, str(batch_export.id), note=note)
        except ValueError:
            raise ValidationError("Cannot pause a BatchExport that is already paused")

        return response.Response({"paused": True})

    @action(methods=["GET"], detail=True)
    def runs(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Get all BatchExportRuns for a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        batch_export = self.get_object()
        runs = BatchExportRun.objects.filter(batch_export=batch_export).order_by("-created_at")

        page = self.paginate_queryset(runs)
        if page is not None:
            serializer = BatchExportRunSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = BatchExportRunSerializer(runs, many=True)
        return response.Response(serializer.data)

    def perform_destroy(self, instance: BatchExport):
        """Perform a BatchExport destroy by clearing Temporal and Django state."""
        instance.deleted = True
        temporal = sync_connect()
        delete_schedule(temporal, str(instance.pk))
        instance.save()
