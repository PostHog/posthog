from django.conf import settings
from django.db import IntegrityError, models, transaction

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
from temporalio.common import RetryPolicy

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import MaterializationType, MaterializedColumnSlot, MaterializedColumnSlotState
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.property_definition import PropertyDefinition
from posthog.permissions import IsStaffUserOrImpersonating
from posthog.settings import EE_AVAILABLE
from posthog.temporal.backfill_materialized_property.activities import (
    MATERIALIZABLE_PROPERTY_TYPES,
    PROPERTY_TYPE_TO_COLUMN_NAME,
)
from posthog.temporal.backfill_materialized_property.workflows import BackfillMaterializedPropertyInputs
from posthog.temporal.common.client import async_connect
from posthog.temporal.eav_backfill.workflows import BackfillEAVPropertyWorkflowInputs

if EE_AVAILABLE:
    from ee.clickhouse.materialized_columns.columns import get_materialized_columns

logger = structlog.get_logger(__name__)


def get_auto_materialized_property_names() -> set[str]:
    """Get set of property names that are already auto-materialized by PostHog."""
    if not EE_AVAILABLE:
        return set()

    try:
        materialized_columns = get_materialized_columns("events")
        return {col.details.property_name for col in materialized_columns.values()}
    except Exception as e:
        logger.warning("Failed to get auto-materialized columns", error=str(e))
        return set()


class AvailablePropertySerializer(serializers.ModelSerializer):
    """Serializer for property definitions available for materialization."""

    class Meta:
        model = PropertyDefinition
        fields = ["id", "name", "property_type", "type"]
        read_only_fields = ["id", "name", "property_type", "type"]


class MaterializedColumnSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaterializedColumnSlot
        fields = [
            "id",
            "team",
            "property_name",
            "property_type",
            "slot_index",
            "state",
            "materialization_type",
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


class MaterializedColumnSlotViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = MaterializedColumnSlot.objects.all().select_related("team")
    permission_classes = [IsStaffUserOrImpersonating]
    serializer_class = MaterializedColumnSlotSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).order_by("property_type", "slot_index")

    @action(methods=["GET"], detail=False)
    def slot_usage(self, request, **kwargs):
        """Get DMAT slot usage summary for a team.

        Only counts DMAT slots since EAV doesn't use the limited slot system.
        """
        counts = {
            row["property_type"]: row["count"]
            for row in MaterializedColumnSlot.objects.filter(
                team_id=self.team_id,
                materialization_type=MaterializationType.DMAT,
            )
            .values("property_type")
            .annotate(count=models.Count("id"))
        }
        usage = {}
        for prop_type in MATERIALIZABLE_PROPERTY_TYPES:
            used = counts.get(prop_type, 0)
            usage[prop_type] = {"used": used, "total": 10, "available": 10 - used}

        return response.Response(
            {
                "team_id": self.team_id,
                "team_name": self.team.name,
                "usage": usage,
            }
        )

    @action(methods=["GET"], detail=False)
    def available_properties(self, request, **kwargs):
        """Get properties that can be materialized for a team.

        Only returns custom properties and feature flag properties.
        Excludes PostHog system properties and properties already auto-materialized.
        """
        already_materialized_names = set(
            MaterializedColumnSlot.objects.filter(team_id=self.team_id).values_list("property_name", flat=True)
        )
        auto_materialized_property_names = get_auto_materialized_property_names()

        available_properties = PropertyDefinition.objects.filter(
            team_id=self.team_id,
            property_type__isnull=False,
            property_type__in=MATERIALIZABLE_PROPERTY_TYPES,
            type=PropertyDefinition.Type.EVENT,
        ).order_by("property_type", "name")

        # Filter out:
        # 1. PostHog system properties (starting with $) except feature flags ($feature/)
        # 2. Properties already auto-materialized by PostHog
        # 3. Properties already materialized by user
        filtered_properties = [
            prop
            for prop in available_properties
            if (not prop.name.startswith("$") or prop.name.startswith("$feature/"))
            and prop.name not in auto_materialized_property_names
            and prop.name not in already_materialized_names
        ]

        return response.Response(AvailablePropertySerializer(filtered_properties, many=True).data)

    @action(methods=["GET"], detail=False)
    def auto_materialized(self, request, **kwargs):
        """Get properties that PostHog has automatically materialized.

        These are managed by PostHog's automatic materialization system and cannot be modified here.
        Uses the same cached function that HogQL uses for query rewriting.
        """
        if not EE_AVAILABLE:
            return response.Response([])

        try:
            # Get all auto-materialized columns using the cached function
            # This is the same cache that HogQL uses (15 minute TTL with background refresh)
            materialized_columns = get_materialized_columns("events")

            # Only show properties column materialized columns (exclude person_properties)
            results = []
            for column in materialized_columns.values():
                if column.details.table_column == "properties":
                    results.append(
                        {
                            "column_name": column.name,
                            "property_name": column.details.property_name,
                            "table_column": column.details.table_column,
                            "is_disabled": column.details.is_disabled,
                            "is_nullable": column.is_nullable,
                        }
                    )

            return response.Response(results)
        except Exception as e:
            logger.exception("Failed to get auto-materialized columns", error=str(e))
            return response.Response(
                {"error": "An internal error has occurred."}, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _validate_property_for_materialization(
        self,
        property_name: str,
        property_type: str | None,
        existing_slots: list[MaterializedColumnSlot],
        auto_materialized_names: set[str],
    ) -> str | None:
        """Returns error message if property cannot be materialized, None if valid."""
        if not property_type:
            return "Property must have a type set to be materialized"
        if property_type not in MATERIALIZABLE_PROPERTY_TYPES:
            return f"Property type '{property_type}' cannot be materialized"
        if property_name.startswith("$") and not property_name.startswith("$feature/"):
            return "PostHog system properties cannot be materialized"
        if property_name in auto_materialized_names:
            return f"Property '{property_name}' is already auto-materialized by PostHog"
        if any(slot.property_name == property_name for slot in existing_slots):
            return "Property is already materialized"
        return None

    def _find_available_slot_index(
        self, property_type: str, existing_slots: list[MaterializedColumnSlot]
    ) -> int | None:
        """Find the next available DMAT slot index for a property type.

        Only considers DMAT slots since EAV slots don't use the slot index system.
        """
        used_indices = {
            slot.slot_index
            for slot in existing_slots
            if slot.property_type == property_type and slot.materialization_type == MaterializationType.DMAT
        }
        for i in range(10):
            if i not in used_indices:
                return i
        return None

    def _get_mat_column_name(self, property_type: str, slot_index: int) -> str:
        """Generate the materialized column name for a slot."""
        type_name = PROPERTY_TYPE_TO_COLUMN_NAME[property_type]
        return f"dmat_{type_name}_{slot_index}"

    def _start_backfill_workflow(
        self,
        slot: MaterializedColumnSlot,
        property_name: str,
        property_type: str,
        workflow_id_suffix: str = "",
    ) -> str | None:
        """Start the Temporal backfill workflow. Returns error message on failure, None on success."""

        async def _start():
            client = await async_connect()

            workflow_input: BackfillEAVPropertyWorkflowInputs | BackfillMaterializedPropertyInputs

            # Choose workflow based on materialization type
            if slot.materialization_type == MaterializationType.EAV:
                workflow_name = "backfill-eav-property"
                workflow_id = f"backfill-eav-prop-{slot.id}{workflow_id_suffix}"
                workflow_input = BackfillEAVPropertyWorkflowInputs(
                    team_id=slot.team_id,
                    slot_id=str(slot.id),
                    property_name=property_name,
                    property_type=property_type,
                )
            else:
                # DMAT workflow
                mat_column_name = self._get_mat_column_name(property_type, slot.slot_index)
                workflow_name = "backfill-materialized-property"
                workflow_id = f"backfill-mat-prop-{slot.id}{workflow_id_suffix}"
                workflow_input = BackfillMaterializedPropertyInputs(
                    team_id=slot.team_id,
                    slot_id=str(slot.id),
                    property_name=property_name,
                    property_type=property_type,
                    mat_column_name=mat_column_name,
                )

            handle = await client.start_workflow(
                workflow_name,
                workflow_input,
                id=workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return handle.id

        try:
            workflow_id = async_to_sync(_start)()
            slot.backfill_temporal_workflow_id = workflow_id
            slot.save()
            logger.info(
                "Started backfill workflow",
                slot_id=slot.id,
                team_id=slot.team_id,
                workflow_id=workflow_id,
                materialization_type=slot.materialization_type,
            )
            return None
        except Exception as e:
            logger.exception(
                "Failed to start backfill workflow",
                slot_id=slot.id,
                team_id=slot.team_id,
                error=str(e),
            )
            return "Failed to start backfill workflow due to an internal error."

    def _log_slot_created(self, slot: MaterializedColumnSlot, request) -> None:
        """Log activity for slot creation."""
        log_activity(
            organization_id=self.team.organization_id,
            team_id=self.team_id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            item_id=str(slot.id),
            scope="DataManagement",
            activity="materialized_column_created",
            detail=Detail(name=slot.property_name),
        )

    @action(methods=["POST"], detail=False)
    def assign_slot(self, request, **kwargs):
        """Assign a property to an available slot.

        Accepts either property_name + property_type directly, or property_definition_id
        to look up the name and type from the property definition.
        """
        property_name = request.data.get("property_name")
        property_type = request.data.get("property_type")
        property_definition_id = request.data.get("property_definition_id")

        # Support both direct property_name/property_type and legacy property_definition_id
        if property_definition_id and not property_name:
            try:
                property_definition = PropertyDefinition.objects.get(id=property_definition_id, team_id=self.team_id)
                property_name = property_definition.name
                property_type = property_definition.property_type
            except PropertyDefinition.DoesNotExist:
                return response.Response({"error": "Property definition not found"}, status=404)

        if not property_name:
            return response.Response({"error": "property_name is required"}, status=400)
        if not property_type:
            return response.Response({"error": "property_type is required"}, status=400)

        # Validate type matches PropertyDefinition if it exists (can't change type after EAV slot created)
        if not property_definition_id:
            existing_definition = PropertyDefinition.objects.filter(
                team_id=self.team_id,
                name=property_name,
                type=PropertyDefinition.Type.EVENT,
            ).first()
            if existing_definition and existing_definition.property_type:
                if existing_definition.property_type != property_type:
                    return response.Response(
                        {
                            "error": f"Property type mismatch: property '{property_name}' is defined as "
                            f"'{existing_definition.property_type}' but you specified '{property_type}'"
                        },
                        status=400,
                    )

        # Parse materialization type, default to DMAT for backwards compatibility
        materialization_type_str = request.data.get("materialization_type", MaterializationType.DMAT)
        try:
            materialization_type = MaterializationType(materialization_type_str)
        except ValueError:
            return response.Response(
                {"error": f"Invalid materialization_type. Must be one of: {[t.value for t in MaterializationType]}"},
                status=400,
            )

        # Fetch auto-materialized names outside transaction (ClickHouse query)
        auto_materialized_names = get_auto_materialized_property_names()

        try:
            with transaction.atomic():
                existing_slots = list(MaterializedColumnSlot.objects.select_for_update().filter(team_id=self.team_id))

                validation_error = self._validate_property_for_materialization(
                    property_name, property_type, existing_slots, auto_materialized_names
                )
                if validation_error:
                    return response.Response({"error": validation_error}, status=400)

                # For DMAT, we need a slot index. For EAV, slot_index is not used (set to 0)
                if materialization_type == MaterializationType.DMAT:
                    slot_index = self._find_available_slot_index(property_type, existing_slots)
                    if slot_index is None:
                        return response.Response(
                            {"error": f"No available slots for property type {property_type}"},
                            status=400,
                        )
                else:
                    # EAV doesn't use slot indexes
                    slot_index = 0

                slot = MaterializedColumnSlot.objects.create(
                    team=self.team,
                    property_name=property_name,
                    property_type=property_type,
                    slot_index=slot_index,
                    state=MaterializedColumnSlotState.BACKFILL,
                    materialization_type=materialization_type,
                    created_by=request.user,
                )

        except IntegrityError:
            return response.Response(
                {"error": "Conflict detected. Please refresh and try again."},
                status=http_status.HTTP_409_CONFLICT,
            )

        # Start workflow outside transaction (idempotent, slot already committed)
        workflow_error = self._start_backfill_workflow(
            slot,
            property_name=property_name,
            property_type=property_type,
        )
        if workflow_error:
            return response.Response({"error": workflow_error}, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

        self._log_slot_created(slot, request)
        return response.Response(MaterializedColumnSlotSerializer(slot).data, status=http_status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """Delete a materialized column slot with activity logging."""
        slot = self.get_object()

        # Prevent deletion during active backfill
        if slot.state == MaterializedColumnSlotState.BACKFILL:
            return response.Response(
                {"error": "Cannot delete slot while backfill is in progress. Wait for completion or failure."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        property_name = slot.property_name

        log_activity(
            organization_id=slot.team.organization_id,
            team_id=slot.team_id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            item_id=str(slot.id),
            scope="DataManagement",
            activity="materialized_column_deleted",
            detail=Detail(name=property_name),
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
    def retry_backfill(self, request, pk=None, **kwargs):
        """Retry backfill for a slot in ERROR state."""
        slot = self.get_object()

        if slot.state != MaterializedColumnSlotState.ERROR:
            return response.Response(
                {"error": f"Can only retry slots in ERROR state. Current state: {slot.state}"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        property_name = slot.property_name
        property_type = slot.property_type

        # Update state back to BACKFILL and clear error message
        slot.state = MaterializedColumnSlotState.BACKFILL
        slot.error_message = None
        slot.save()

        workflow_error = self._start_backfill_workflow(
            slot,
            property_name=property_name,
            property_type=property_type,
            workflow_id_suffix=f"-retry-{slot.updated_at.timestamp()}",
        )
        if workflow_error:
            # Revert state and record the new error
            slot.state = MaterializedColumnSlotState.ERROR
            slot.error_message = workflow_error
            slot.save()
            return response.Response({"error": workflow_error}, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

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
