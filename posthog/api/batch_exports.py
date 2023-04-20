from asgiref.sync import async_to_sync
from django.conf import settings
from rest_framework import permissions, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleState,
)

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.export import ExportDestination, ExportRun, ExportSchedule
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team import Team
from posthog.temporal.client import connect


@async_to_sync
async def get_temporal_client() -> Client:
    """Connect to and return a Temporal Client."""
    client = await connect(
        settings.TEMPORAL_SCHEDULER_HOST, settings.TEMPORAL_SCHEDULER_PORT, settings.TEMPORAL_NAMESPACE
    )
    return client


class ExportRunViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = ExportRun.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    @cached_property
    def schedule(self) -> ExportSchedule:
        workflow_name = self.request.data.get("workflow_name")

        if workflow_name is None:
            raise NotFound(f"Workflow {workflow_name} not found.")

        workflow = ExportSchedule.objects.get_workflow_from_name(name=workflow_name)

        if workflow is None:
            raise NotFound(f"Workflow {workflow_name} not found.")

        return workflow


class ExportDestinationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExportDestination
        fields = [
            "id",
            "type",
            "name",
            "parameters",
        ]
        read_only_fields = ["id", "created_at", "last_updated_at"]


class ExportScheduleSerializer(serializers.ModelSerializer):
    destination = ExportDestinationSerializer()

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

        destination_data = validated_data.pop("destination")
        export_schedule = ExportSchedule.objects.create(
            team=team,
            name=validated_data["name"],
            destination_type=destination_data.get("type", None),
            destination_parameters=destination_data.get("parameters", None),
            destination_name=destination_data.get("name", None),
        )
        schedule_spec = export_schedule.get_schedule_spec()
        destination = export_schedule.destination
        workflow, workflow_inputs = destination.get_temporal_workflow()

        client = get_temporal_client()
        async_to_sync(client.create_schedule)(
            id=export_schedule.name,
            schedule=Schedule(
                action=ScheduleActionStartWorkflow(
                    workflow.run,
                    workflow_inputs(**destination.parameters, team_id=team.id),
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
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ExportScheduleSerializer

    @action(methods=["PUT"], detail=True)
    def unpause(self, request: request.Request) -> response.Response:
        """Unpause an ExportSchedule using the Temporal schedule handle."""
        export_schedule = self.get_object()

        client = get_temporal_client()
        handle = client.get_schedule_handle(
            export_schedule.name,
        )

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
            instance.name,
        )

        async_to_sync(handle.delete)()
        instance.delete()
