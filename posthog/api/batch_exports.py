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
    BatchExportSchedule,
    Team,
    User,
)
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)


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

        return self.queryset.filter(team_id=self.request.user.current_team.id)


class BatchExportDestinationSerializer(serializers.ModelSerializer):
    """Serializer for an BatchExportDestination model."""

    class Meta:
        model = BatchExportDestination
        exclude = ["team"]
        read_only_fields = [
            "id",
            "created_at",
            "last_updated_at",
        ]

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


class BatchExportDestinationViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = BatchExportDestination.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    serializer_class = BatchExportDestinationSerializer

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        return self.queryset.filter(team_id=self.request.user.current_team.id)


class BatchExportScheduleSerializer(serializers.ModelSerializer):
    """Serializer for an BatchExportSchedule model."""

    class Meta:
        model = BatchExportSchedule
        exclude = ["team"]
        read_only_fields = [
            "id",
            "created_at",
            "last_updated_at",
            "paused_at",
            "unpaused_at",
            "start_at",
            "end_at",
        ]

    def create(self, validated_data: dict):
        """Create an BatchExportSchedule model."""
        team = Team.objects.get(id=self.context["team_id"])

        export_schedule = BatchExportSchedule.objects.create(
            team=team,
            **validated_data,
        )

        return export_schedule


class BatchExportSerializer(serializers.ModelSerializer):
    """Serializer for a BatchExport model."""

    destination = BatchExportDestinationSerializer()
    schedule = BatchExportScheduleSerializer()
    runs = serializers.SerializerMethodField()

    class Meta:
        model = BatchExport
        fields = [
            "id",
            "destination",
            "schedule",
            "runs",
            "created_at",
            "last_updated_at",
        ]
        read_only_fields = [
            "id",
            "schedule",
            "runs",
            "created_at",
            "last_updated_at",
        ]

    def create(self, validated_data: dict) -> BatchExport:
        """Create a BatchExport."""
        destination_data = validated_data.pop("destination")
        schedule_data = validated_data.pop("schedule")
        team = Team.objects.get(id=self.context["team_id"])

        destination = BatchExportDestination.objects.create(team=team, **destination_data)
        schedule = BatchExportSchedule.objects.create(team=team, **schedule_data)

        batch_export = BatchExport.objects.create(team=team, schedule=schedule, destination=destination)
        return batch_export

    def get_runs(self, batch_export):
        serializer = BatchExportRunSerializer(BatchExportRun.objects.filter(batch_export=batch_export), many=True)
        return serializer.data


class BatchExportViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = BatchExport.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    serializer_class = BatchExportSerializer

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        return self.queryset.filter(team_id=self.request.user.current_team.id).prefetch_related(
            "destination", "schedule"
        )

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
        batch_export.backfill(start_at, end_at)

        serializer = self.get_serializer(batch_export)
        return response.Response(serializer.data)

    @action(methods=["PATCH"], detail=True)
    def pause(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Pause a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id
        note = f"Unpause requested by user {user_id} from team {team_id}"

        batch_export = self.get_object()
        try:
            batch_export.pause(note=note)
        except ValueError:
            raise ValidationError("Cannot pause a BatchExport that is already paused")

        serializer = self.get_serializer(batch_export)
        return response.Response(serializer.data)

    @action(methods=["PATCH"], detail=True)
    def unpause(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Unpause a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id
        note = f"Unpause requested by user {user_id} from team {team_id}"

        batch_export = self.get_object()
        try:
            batch_export.schedule.unpause(note=note)
        except ValueError:
            raise ValidationError("Cannot unpause a BatchExport that is not paused")

        serializer = self.get_serializer(batch_export)
        return response.Response(serializer.data)

    def perform_destroy(self, instance: BatchExport):
        """Perform a BatchExport destroy by clearing Temporal and Django state."""
        instance.delete_batch_export_schedule()
        instance.delete()
