from asgiref.sync import async_to_sync
from django.conf import settings
from rest_framework import serializers, viewsets, response, permissions, request
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleState,
)

from posthog.temporal.client import connect
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.export import ExportSchedule, ExportRun


async def get_temporal_client() -> Client:
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


class ExportScheduleSerializer(serializers.ModelSerialize):
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
            "spec",
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

    @async_to_sync
    async def create(self, validated_data: dict):
        export_schedule = ExportSchedule.objects.create(
            team=self.team,
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
    include_in_docs = False

    @action(methods=["PUT"], detail=True)
    @async_to_sync
    async def unpause(self, request: request.Request) -> response.Response:
        """Unpause an ExportSchedule using the Temporal schedule handle."""
        export_schedule = self.get_object()

        client = await self.get_temporal_client()
        handle = await client.get_schedule_handle(
            export_schedule.name,
        )

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id

        note = f"Unpause requested by user {user_id} from team {team_id}"
        await handle.unpause(note=note)

        description = await handle.describe_schedule()
        export_schedule.unpaused_at = description.info.last_updated_at
        export_schedule.last_updated_at = description.info.last_updated_at
        export_schedule.save()

    @action(methods=["PUT"], detail=True)
    @async_to_sync
    async def pause(self, request: request.Request) -> response.Response:
        """Pause an ExportSchedule using the Temporal schedule handle."""
        export_schedule = self.get_object()

        client = await self.get_temporal_client()
        handle = await client.get_schedule_handle(
            export_schedule.name,
        )

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id

        note = f"Pause requested by user {user_id} from team {team_id}"
        await handle.pause(note=note)

        description = await handle.describe_schedule()
        export_schedule.paused_at = description.info.last_updated_at
        export_schedule.last_updated_at = description.info.last_updated_at
        export_schedule.save()
