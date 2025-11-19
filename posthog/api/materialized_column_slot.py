from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from loginas.utils import is_impersonated_session
from rest_framework import (
    response,
    serializers,
    status as http_status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from temporalio.common import RetryPolicy

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition, Team
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.property_definition import PropertyType
from posthog.permissions import IsStaffUserOrImpersonating
from posthog.temporal.backfill_materialized_property.workflows import BackfillMaterializedPropertyInputs
from posthog.temporal.common.client import async_connect

logger = structlog.get_logger(__name__)


class PropertyDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyDefinition
        fields = ["id", "name", "property_type", "type"]
        read_only_fields = ["id", "name", "property_type", "type"]


class MaterializedColumnSlotSerializer(serializers.ModelSerializer):
    property_definition_details = PropertyDefinitionSerializer(source="property_definition", read_only=True)

    class Meta:
        model = MaterializedColumnSlot
        fields = [
            "id",
            "team",
            "property_definition",
            "property_definition_details",
            "property_type",
            "slot_index",
            "state",
            "backfill_temporal_workflow_id",
            "error_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]


class MaterializedColumnSlotViewSet(viewsets.ModelViewSet):
    queryset = MaterializedColumnSlot.objects.all().select_related("property_definition", "team")
    permission_classes = [IsAuthenticated, IsStaffUserOrImpersonating]
    serializer_class = MaterializedColumnSlotSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        team_id = self.request.query_params.get("team_id")
        if team_id:
            queryset = queryset.filter(team_id=team_id)
        return queryset.order_by("property_type", "slot_index")

    @action(methods=["GET"], detail=False)
    def slot_usage(self, request):
        """Get slot usage summary for a team."""
        team_id = request.query_params.get("team_id")
        if not team_id:
            return response.Response({"error": "team_id is required"}, status=400)

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            return response.Response({"error": "Team not found"}, status=404)

        # Duration properties are PostHog system properties and should never be materialized
        # This filters them out defensively - if any exist, they indicate a data integrity issue
        allowed_types = [t for t in PropertyType.values if t != PropertyType.Duration]

        # Check for any unexpected Duration slots and log an error
        duration_count = MaterializedColumnSlot.objects.filter(
            team_id=team_id, property_type=PropertyType.Duration
        ).count()
        if duration_count > 0:
            logger.error(
                "Found materialized Duration properties",
                team_id=team_id,
                count=duration_count,
            )

        usage = {}
        for prop_type in allowed_types:
            count = MaterializedColumnSlot.objects.filter(team_id=team_id, property_type=prop_type).count()
            usage[prop_type] = {"used": count, "total": 10, "available": 10 - count}

        return response.Response(
            {
                "team_id": team_id,
                "team_name": team.name,
                "usage": usage,
            }
        )

    @action(methods=["GET"], detail=False)
    def available_properties(self, request):
        """Get properties that can be materialized for a team.

        Only returns custom properties and feature flag properties.
        Excludes PostHog system properties and Duration type properties.
        """
        team_id = request.query_params.get("team_id")
        if not team_id:
            return response.Response({"error": "team_id is required"}, status=400)

        if not Team.objects.filter(id=team_id).exists():
            return response.Response({"error": "Team not found"}, status=404)

        # Get properties that are not already materialized and have a property_type set
        already_materialized = MaterializedColumnSlot.objects.filter(team_id=team_id).values_list(
            "property_definition_id", flat=True
        )

        # Duration properties are PostHog system properties and should never be materialized
        allowed_types = [t for t in PropertyType.values if t != PropertyType.Duration]

        available_properties = (
            PropertyDefinition.objects.filter(
                team_id=team_id, property_type__isnull=False, property_type__in=allowed_types
            )
            .exclude(id__in=already_materialized)
            .order_by("property_type", "name")
        )

        # Filter out PostHog system properties (starting with $) except feature flags ($feature/)
        # Duration properties are implicitly excluded here since they're PostHog system properties
        filtered_properties = [
            prop for prop in available_properties if not prop.name.startswith("$") or prop.name.startswith("$feature/")
        ]

        return response.Response(PropertyDefinitionSerializer(filtered_properties, many=True).data)

    @action(methods=["POST"], detail=False)
    def assign_slot(self, request):
        """Assign a property to an available slot."""
        team_id = request.data.get("team_id")
        property_definition_id = request.data.get("property_definition_id")

        if not team_id or not property_definition_id:
            return response.Response({"error": "team_id and property_definition_id are required"}, status=400)

        try:
            team = Team.objects.get(id=team_id)
            property_definition = PropertyDefinition.objects.get(id=property_definition_id, team_id=team_id)
        except Team.DoesNotExist:
            return response.Response({"error": "Team not found"}, status=404)
        except PropertyDefinition.DoesNotExist:
            return response.Response({"error": "Property definition not found"}, status=404)

        if not property_definition.property_type:
            return response.Response({"error": "Property must have a type set to be materialized"}, status=400)

        # Validate property type is not Duration
        if property_definition.property_type == PropertyType.Duration:
            return response.Response({"error": "Duration properties cannot be materialized"}, status=400)

        # Validate property is not a PostHog system property (except feature flags)
        if property_definition.name.startswith("$") and not property_definition.name.startswith("$feature/"):
            return response.Response({"error": "PostHog system properties cannot be materialized"}, status=400)

        # Check if property is already materialized
        if MaterializedColumnSlot.objects.filter(team_id=team_id, property_definition=property_definition).exists():
            return response.Response({"error": "Property is already materialized"}, status=400)

        # Find next available slot for this property type
        used_slots = set(
            MaterializedColumnSlot.objects.filter(team_id=team_id, property_type=property_definition.property_type)
            .values_list("slot_index", flat=True)
            .distinct()
        )

        available_slot = None
        for i in range(10):
            if i not in used_slots:
                available_slot = i
                break

        if available_slot is None:
            return response.Response(
                {"error": f"No available slots for property type {property_definition.property_type}"}, status=400
            )

        # Create the slot assignment
        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=property_definition,
            property_type=property_definition.property_type,
            slot_index=available_slot,
            state=MaterializedColumnSlotState.BACKFILL,
            created_by=request.user,
        )

        # Start Temporal backfill workflow
        async def _start_backfill():
            client = await async_connect()
            workflow_id = f"backfill-mat-prop-{slot.id}"
            handle = await client.start_workflow(
                "backfill-materialized-property",
                BackfillMaterializedPropertyInputs(
                    team_id=team_id,
                    slot_id=str(slot.id),
                ),
                id=workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return handle.id

        try:
            workflow_id = async_to_sync(_start_backfill)()
            slot.backfill_temporal_workflow_id = workflow_id
            slot.save()

            logger.info(
                "Started backfill workflow",
                slot_id=slot.id,
                team_id=team_id,
                workflow_id=workflow_id,
                property_name=property_definition.name,
            )
        except Exception as e:
            logger.exception(
                "Failed to start backfill workflow",
                slot_id=slot.id,
                team_id=team_id,
                property_name=property_definition.name,
                error=str(e),
            )
            # Don't delete the slot, leave it in BACKFILL state so user can retry
            # Return error so user knows workflow didn't start
            return response.Response(
                {"error": f"Failed to start backfill workflow: {str(e)}"},
                status=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Log activity
        log_activity(
            organization_id=team.organization_id,
            team_id=team_id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            item_id=str(slot.id),
            scope="DataManagement",
            activity="materialized_column_created",
            detail=Detail(
                name=property_definition.name,
                changes=[
                    Change(
                        type="MaterializedColumnSlot",
                        action="created",
                        field="property",
                        after=property_definition.name,
                    ),
                    Change(
                        type="MaterializedColumnSlot",
                        action="created",
                        field="property_type",
                        after=property_definition.property_type,
                    ),
                    Change(
                        type="MaterializedColumnSlot",
                        action="created",
                        field="slot_index",
                        after=available_slot,
                    ),
                ],
            ),
        )

        return response.Response(MaterializedColumnSlotSerializer(slot).data, status=http_status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """Delete a materialized column slot with activity logging."""
        slot = self.get_object()
        property_name = slot.property_definition.name if slot.property_definition else "Unknown"

        # Log activity before deletion
        log_activity(
            organization_id=slot.team.organization_id,
            team_id=slot.team_id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            item_id=str(slot.id),
            scope="DataManagement",
            activity="materialized_column_deleted",
            detail=Detail(
                name=property_name,
                changes=[
                    Change(
                        type="MaterializedColumnSlot",
                        action="deleted",
                        field="property",
                        before=property_name,
                    ),
                    Change(
                        type="MaterializedColumnSlot",
                        action="deleted",
                        field="property_type",
                        before=slot.property_type,
                    ),
                    Change(
                        type="MaterializedColumnSlot",
                        action="deleted",
                        field="slot_index",
                        before=slot.slot_index,
                    ),
                ],
            ),
        )

        logger.info(
            "Deleted materialized column slot",
            slot_id=slot.id,
            team_id=slot.team_id,
            property_name=property_name,
        )

        # Perform deletion
        slot.delete()

        return response.Response(status=http_status.HTTP_204_NO_CONTENT)

    @action(methods=["POST"], detail=True)
    def retry_backfill(self, request, pk=None):
        """Retry backfill for a slot in ERROR state."""
        slot = self.get_object()

        if slot.state != MaterializedColumnSlotState.ERROR:
            return response.Response(
                {"error": f"Can only retry slots in ERROR state. Current state: {slot.state}"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        property_name = slot.property_definition.name if slot.property_definition else "Unknown"

        # Update state back to BACKFILL and clear error message
        slot.state = MaterializedColumnSlotState.BACKFILL
        slot.error_message = None
        slot.save()

        # Start new Temporal backfill workflow
        async def _start_backfill():
            client = await async_connect()
            workflow_id = f"backfill-mat-prop-{slot.id}-retry-{slot.updated_at.timestamp()}"
            handle = await client.start_workflow(
                "backfill-materialized-property",
                BackfillMaterializedPropertyInputs(
                    team_id=slot.team_id,
                    slot_id=str(slot.id),
                ),
                id=workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return handle.id

        try:
            workflow_id = async_to_sync(_start_backfill)()
            slot.backfill_temporal_workflow_id = workflow_id
            slot.save()

            logger.info(
                "Retried backfill workflow",
                slot_id=slot.id,
                team_id=slot.team_id,
                workflow_id=workflow_id,
                property_name=property_name,
            )
        except Exception as e:
            logger.exception(
                "Failed to retry backfill workflow",
                slot_id=slot.id,
                team_id=slot.team_id,
                property_name=property_name,
                error=str(e),
            )
            # Revert state back to ERROR
            slot.state = MaterializedColumnSlotState.ERROR
            slot.save()

            return response.Response(
                {"error": f"Failed to retry backfill workflow: {str(e)}"},
                status=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Log activity
        log_activity(
            organization_id=slot.team.organization_id,
            team_id=slot.team_id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            item_id=str(slot.id),
            scope="DataManagement",
            activity="materialized_column_retried",
            detail=Detail(
                name=property_name,
                changes=[
                    Change(
                        type="MaterializedColumnSlot",
                        action="changed",
                        field="state",
                        before="ERROR",
                        after="BACKFILL",
                    ),
                ],
            ),
        )

        return response.Response(MaterializedColumnSlotSerializer(slot).data)
