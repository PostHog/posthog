from asgiref.sync import async_to_sync
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import (
    BatchExportDestination,
    BatchExportRun,
    BatchExportSchedule,
    User,
)
from posthog.models.team import Team
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)
from posthog.temporal.client import sync_connect


class BatchExportRunViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = BatchExportRun.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]


class BatchExportScheduleSerializer(serializers.ModelSerializer):
    """Serializer for an BatchExportSchedule model."""

    destination = serializers.PrimaryKeyRelatedField(queryset=BatchExportDestination.objects.all(), required=False)
    paused_at = serializers.DateTimeField(required=False)
    unpaused_at = serializers.DateTimeField(required=False)
    start_at = serializers.DateTimeField(required=False)
    end_at = serializers.DateTimeField(required=False)

    class Meta:
        model = BatchExportSchedule
        fields = [
            "id",
            "name",
            "destination",
            "created_at",
            "last_updated_at",
            "paused_at",
            "unpaused_at",
            "start_at",
            "end_at",
            "calendars",
            "intervals",
            "cron_expressions",
            "skip",
            "jitter",
            "time_zone_name",
        ]
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
        destination = BatchExportDestination.objects.get(id=self.context["destination_id"])

        export_schedule = BatchExportSchedule.objects.create(
            team=team,
            destination=destination,
            **validated_data,
        )

        return export_schedule


class BatchExportScheduleViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = BatchExportSchedule.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    serializer_class = BatchExportScheduleSerializer

    @action(methods=["PUT"], detail=True)
    def unpause(self, request: request.Request) -> response.Response:
        """Unpause an BatchExportSchedule using the Temporal schedule handle."""
        export_schedule = self.get_object()

        client = sync_connect()
        handle = client.get_schedule_handle(
            export_schedule.name,
        )

        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id

        note = f"Unpause requested by user {user_id} from team {team_id}"
        async_to_sync(handle.unpause)(note=note)

        description = async_to_sync(handle.describe)()
        export_schedule.unpaused_at = description.info.last_updated_at
        export_schedule.last_updated_at = description.info.last_updated_at
        export_schedule.save()

        serializer = self.get_serializer(export_schedule)
        return response.Response(serializer.data)

    @action(methods=["PUT"], detail=True)
    def pause(self, request: request.Request) -> response.Response:
        """Pause an BatchExportSchedule using the Temporal schedule handle."""
        export_schedule = self.get_object()

        client = sync_connect()
        handle = client.get_schedule_handle(
            export_schedule.name,
        )

        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id

        note = f"Pause requested by user {user_id} from team {team_id}"
        async_to_sync(handle.pause)(note=note)

        description = async_to_sync(handle.describe)()
        export_schedule.paused_at = description.info.last_updated_at
        export_schedule.last_updated_at = description.info.last_updated_at
        export_schedule.save()

        serializer = self.get_serializer(export_schedule)
        return response.Response(serializer.data)

    def perform_destroy(self, instance: BatchExportSchedule):
        """Perform a BatchExportSchedule destroy by clearing it from Temporal and Django."""
        client = sync_connect()
        handle = client.get_schedule_handle(
            str(instance.id),
        )

        async_to_sync(handle.delete)()
        instance.delete()


class BatchExportDestinationSerializer(serializers.ModelSerializer):
    """Serializer for an BatchExportDestination model."""

    schedule = BatchExportScheduleSerializer(required=False)

    class Meta:
        model = BatchExportDestination
        fields = [
            "id",
            "type",
            "name",
            "config",
            "team_id",
            "schedule",
        ]
        read_only_fields = ["id", "created_at", "last_updated_at", "schedules"]

    def create(self, validated_data: dict):
        """Create an BatchExportDestination, optionally with an BatchExportSchedule."""

        team = Team.objects.get(id=self.context["team_id"])
        schedule_data = validated_data.pop("schedule")

        export_destination = BatchExportDestination.objects.create(team_id=self.context["team_id"], **validated_data)

        if schedule_data:
            schedule = BatchExportSchedule.objects.create(team=team, destination=export_destination, **schedule_data)
            export_destination.schedule = schedule

        export_destination.save()

        return export_destination


class BatchExportDestinationViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = BatchExportDestination.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    serializer_class = BatchExportDestinationSerializer

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        return self.queryset.filter(team_id=self.request.user.current_team.id)
