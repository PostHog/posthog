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
from posthog.models.export import ExportRun, ExportSchedule
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team import Team
from posthog.temporal.client import connect


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


class ExportScheduleSerializer(serializers.ModelSerializer):
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
            "destination",
            "calendars",
            "intervals",
            "cron_expressions",
            "skip",
            "jitter",
            "time_zone_name",
        ]
        read_only_fields = [
            "id",
            "destination",
            "created_at",
            "last_updated_at",
            "paused_at",
            "unpaused_at",
            "start_at",
            "end_at",
        ]

    @async_to_sync
    async def create(self, validated_data: dict):
        """Create an ExportSchedule model and in Temporal."""
        team = Team.objects.get(id=self.context["team_id"])
        export_schedule = ExportSchedule.objects.create(
            team=team,
            name=validated_data["name"],
            destination_type=validated_data["destination"].get("type", None),
            destination_parameters=validated_data["destination"].get("parameters", None),
            destination_name=validated_data["destination"].get("name", None),
        )
        schedule_spec = export_schedule.get_schedule_spec()
        destination = export_schedule.destination
        workflow, workflow_inputs = destination.get_workflow()

        client = await get_temporal_client()
        await client.create_schedule(
            id=export_schedule.name,
            schedule=Schedule(
                action=ScheduleActionStartWorkflow(
                    workflow.run,
                    workflow_inputs(**destination.parameters),
                    id=f"{export_schedule.team.id}-{destination.type}-export",
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                ),
                spec=schedule_spec,
                state=ScheduleState(note="Schedule created."),
            ),
        )


class ExportScheduleViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = ExportSchedule.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ExportScheduleSerializer

    @action(methods=["PUT"], detail=True)
    @async_to_sync
    async def unpause(self, request: request.Request) -> response.Response:
        """Unpause an ExportSchedule using the Temporal schedule handle."""
        export_schedule = self.get_object()

        client = await get_temporal_client()
        handle = client.get_schedule_handle(
            export_schedule.name,
        )

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id

        note = f"Unpause requested by user {user_id} from team {team_id}"
        await handle.unpause(note=note)

        description = await handle.describe()
        export_schedule.unpaused_at = description.info.last_updated_at
        export_schedule.last_updated_at = description.info.last_updated_at
        export_schedule.save()

        serializer = self.get_serializer(export_schedule)
        return response.Response(serializer.data)

    @action(methods=["PUT"], detail=True)
    @async_to_sync
    async def pause(self, request: request.Request) -> response.Response:
        """Pause an ExportSchedule using the Temporal schedule handle."""
        export_schedule = self.get_object()

        client = await get_temporal_client()
        handle = client.get_schedule_handle(
            export_schedule.name,
        )

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id

        note = f"Pause requested by user {user_id} from team {team_id}"
        await handle.pause(note=note)

        description = await handle.describe()
        export_schedule.paused_at = description.info.last_updated_at
        export_schedule.last_updated_at = description.info.last_updated_at
        export_schedule.save()

        serializer = self.get_serializer(export_schedule)
        return response.Response(serializer.data)

    @async_to_sync
    async def perform_destroy(self, instance: ExportSchedule):
        """Perform a ExportSchedule destroy by clearing it from Temporal and Django."""
        client = await get_temporal_client()
        handle = client.get_schedule_handle(
            instance.name,
        )

        await handle.delete()
        instance.delete()
