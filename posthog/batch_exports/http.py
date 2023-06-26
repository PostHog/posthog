import datetime as dt

from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated, ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.batch_exports.service import (
    backfill_export,
    create_batch_export,
    delete_schedule,
    pause_batch_export,
    reset_batch_export_run,
    unpause_batch_export,
)
from posthog.models import (
    BatchExport,
    BatchExportDestination,
    BatchExportRun,
    User,
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


class BatchExportRunViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = BatchExportRun.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    serializer_class = BatchExportRunSerializer

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        return self.queryset.filter(batch_export_id=self.kwargs["parent_lookup_batch_export_id"]).order_by(
            "-created_at"
        )

    def list(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Get all BatchExportRuns for a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        runs = self.get_queryset()

        limit = self.request.query_params.get("limit", None)
        if limit is not None:
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                raise ValidationError(f"Invalid value for 'limit' parameter: '{limit}'")

            runs = runs[:limit]

        page = self.paginate_queryset(runs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(runs, many=True)
        return response.Response(serializer.data)

    @action(methods=["POST"], detail=True)
    def reset(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Reset a BatchExportRun by resetting its associated Temporal Workflow."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        batch_export_run = self.get_object()
        temporal = sync_connect()

        scheduled_id = f"{batch_export_run.batch_export.id}-{batch_export_run.data_interval_end:%Y-%m-%dT%H:%M:%SZ}"
        new_run_id = reset_batch_export_run(temporal, batch_export_id=scheduled_id)

        return response.Response({"new_run_id": new_run_id})


class BatchExportDestinationSerializer(serializers.ModelSerializer):
    """Serializer for an BatchExportDestination model."""

    class Meta:
        model = BatchExportDestination
        fields = ["type", "config"]

    def create(self, validated_data: dict) -> BatchExportDestination:
        """Create a BatchExportDestination."""
        export_destination = BatchExportDestination.objects.create(**validated_data)
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

    def perform_destroy(self, instance: BatchExport):
        """Perform a BatchExport destroy by clearing Temporal and Django state."""
        instance.deleted = True
        temporal = sync_connect()
        delete_schedule(temporal, str(instance.pk))
        instance.save()
