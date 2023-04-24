from asgiref.sync import async_to_sync
from django.conf import settings
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleState,
)

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import ExportDestination, ExportRun, ExportSchedule, User
from posthog.models.team import Team
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)
from posthog.temporal.client import connect
from posthog.temporal.workflows import DESTINATION_WORKFLOWS


@async_to_sync
async def get_temporal_client() -> Client:
    """Connect to and return a Temporal Client."""
    client = await connect(
        settings.TEMPORAL_SCHEDULER_HOST, settings.TEMPORAL_SCHEDULER_PORT, settings.TEMPORAL_NAMESPACE
    )
    return client


class ExportRunViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = ExportRun.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]


class ExportScheduleSerializer(serializers.ModelSerializer):
    """Serializer for an ExportSchedule model.

    This Serializer holds the responsibility of interacting with Temporal when required.
    """

    destination = serializers.PrimaryKeyRelatedField(queryset=ExportDestination.objects.all(), required=False)
    paused_at = serializers.DateTimeField(required=False)
    unpaused_at = serializers.DateTimeField(required=False)
    start_at = serializers.DateTimeField(required=False)
    end_at = serializers.DateTimeField(required=False)

    class Meta:
        model = ExportSchedule
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
        """Create an ExportSchedule model and in Temporal."""
        team = Team.objects.get(id=self.context["team_id"])
        destination = ExportDestination.objects.get(id=self.context["destination_id"])

        export_schedule = ExportSchedule.objects.create(
            team=team,
            destination=destination,
            **validated_data,
        )
        schedule_spec = export_schedule.get_schedule_spec()
        destination = export_schedule.destination
        workflow, workflow_inputs = DESTINATION_WORKFLOWS[destination.type]

        client = get_temporal_client()
        async_to_sync(client.create_schedule)(
            id=str(export_schedule.id),
            schedule=Schedule(
                action=ScheduleActionStartWorkflow(
                    workflow.run,
                    workflow_inputs(team_id=team.id, **destination.config),
                    id=f"{export_schedule.team.id}-{destination.type}-export",
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                ),
                spec=schedule_spec,
                state=ScheduleState(note="Schedule created."),
            ),
        )

        return export_schedule


class ExportScheduleViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = ExportSchedule.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    serializer_class = ExportScheduleSerializer

    @action(methods=["PUT"], detail=True)
    def unpause(self, request: request.Request) -> response.Response:
        """Unpause an ExportSchedule using the Temporal schedule handle."""
        export_schedule = self.get_object()

        client = get_temporal_client()
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
        """Pause an ExportSchedule using the Temporal schedule handle."""
        export_schedule = self.get_object()

        client = get_temporal_client()
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

    def perform_destroy(self, instance: ExportSchedule):
        """Perform a ExportSchedule destroy by clearing it from Temporal and Django."""
        client = get_temporal_client()
        handle = client.get_schedule_handle(
            str(instance.id),
        )

        async_to_sync(handle.delete)()
        instance.delete()


class ExportDestinationSerializer(serializers.ModelSerializer):
    schedule = ExportScheduleSerializer()

    class Meta:
        model = ExportDestination
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
        schedule_data = validated_data.pop("schedule")
        export_destination = ExportDestination.objects.create(team_id=self.context["team_id"], **validated_data)

        team = Team.objects.get(id=self.context["team_id"])

        schedule = ExportSchedule.objects.create(destination=export_destination, team=team, **schedule_data)
        export_destination.schedule = schedule
        export_destination.save()

        return export_destination


class ExportDestinationViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = ExportDestination.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    serializer_class = ExportDestinationSerializer

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        return self.queryset.filter(team_id=self.request.user.current_team.id)
