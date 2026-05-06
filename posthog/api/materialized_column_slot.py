from django.db import IntegrityError, transaction

import structlog
from loginas.utils import is_impersonated_session
from rest_framework import (
    response,
    serializers,
    status as http_status,
    viewsets,
)
from rest_framework.decorators import action

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.materialized_column_slots import MAX_SLOTS_PER_TEAM
from posthog.permissions import IsStaffUserOrImpersonating
from posthog.settings import EE_AVAILABLE

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
            "slot_index",
            "compaction_target_slot_index",
            "state",
            "backfill_temporal_run_id",
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
    queryset = MaterializedColumnSlot.objects.all().select_related("property_definition", "team")
    permission_classes = [IsStaffUserOrImpersonating]
    serializer_class = MaterializedColumnSlotSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).order_by("slot_index")

    @action(methods=["GET"], detail=False)
    def slot_usage(self, request, **kwargs):
        """Per-team materialized column slot usage.

        The cap is MAX_SLOTS_PER_TEAM across all properties — there is no per-type
        breakdown because dmat is string-only (HogQL casts at read time).
        """
        used_total = MaterializedColumnSlot.objects.filter(team_id=self.team_id).count()
        available = max(0, MAX_SLOTS_PER_TEAM - used_total)
        return response.Response(
            {
                "team_id": self.team_id,
                "team_name": self.team.name,
                "max_slots_per_team": MAX_SLOTS_PER_TEAM,
                "used_total": used_total,
                "available": available,
            }
        )

    @action(methods=["GET"], detail=False)
    def available_properties(self, request, **kwargs):
        """Get properties that can be materialized for a team.

        Only returns custom properties and feature flag properties.
        Excludes PostHog system properties and properties already auto-materialized.
        """
        already_materialized = MaterializedColumnSlot.objects.filter(team_id=self.team_id).values_list(
            "property_definition_id", flat=True
        )
        auto_materialized_property_names = get_auto_materialized_property_names()

        available_properties = (
            PropertyDefinition.objects.filter(
                team_id=self.team_id,
                property_type__isnull=False,
                type=PropertyDefinition.Type.EVENT,
            )
            .exclude(id__in=already_materialized)
            .order_by("property_type", "name")
        )

        # Filter out:
        # 1. PostHog system properties (starting with $) except feature flags ($feature/)
        # 2. Properties already auto-materialized by PostHog
        filtered_properties = [
            prop
            for prop in available_properties
            if (not prop.name.startswith("$") or prop.name.startswith("$feature/"))
            and prop.name not in auto_materialized_property_names
        ]

        return response.Response(PropertyDefinitionSerializer(filtered_properties, many=True).data)

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
        property_definition: PropertyDefinition,
        existing_slots: list[MaterializedColumnSlot],
        auto_materialized_names: set[str],
    ) -> str | None:
        """Returns error message if property cannot be materialized, None if valid."""
        if not property_definition.property_type:
            return "Property must have a type set to be materialized"
        if property_definition.name.startswith("$") and not property_definition.name.startswith("$feature/"):
            return "PostHog system properties cannot be materialized"
        if property_definition.name in auto_materialized_names:
            return f"Property '{property_definition.name}' is already auto-materialized by PostHog"
        if any(slot.property_definition_id == property_definition.id for slot in existing_slots):
            return "Property is already materialized"
        if len(existing_slots) >= MAX_SLOTS_PER_TEAM:
            return f"Team has reached the maximum of {MAX_SLOTS_PER_TEAM} materialized column slots"
        return None

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
            detail=Detail(name=slot.property_definition.name),
        )

    @action(methods=["POST"], detail=False)
    def assign_slot(self, request, **kwargs):
        """Queue a property for materialization.

        The slot is created in PENDING state with no slot_index assigned. The weekly
        batched workflow assigns a column index, runs the historical backfill, and
        transitions the slot to READY. Until then HogQL falls back to JSON extraction
        for this property.
        """
        property_definition_id = request.data.get("property_definition_id")
        if not property_definition_id:
            return response.Response({"error": "property_definition_id is required"}, status=400)

        auto_materialized_names = get_auto_materialized_property_names()

        try:
            with transaction.atomic():
                property_definition = PropertyDefinition.objects.select_for_update().get(
                    id=property_definition_id, team_id=self.team_id
                )
                existing_slots = list(MaterializedColumnSlot.objects.filter(team_id=self.team_id))

                validation_error = self._validate_property_for_materialization(
                    property_definition, existing_slots, auto_materialized_names
                )
                if validation_error:
                    return response.Response({"error": validation_error}, status=400)

                slot = MaterializedColumnSlot.objects.create(
                    team=self.team,
                    property_definition=property_definition,
                    slot_index=None,
                    state=MaterializedColumnSlotState.PENDING,
                    created_by=request.user,
                )

        except PropertyDefinition.DoesNotExist:
            return response.Response({"error": "Property definition not found"}, status=404)
        except IntegrityError:
            return response.Response(
                {"error": "Conflict detected. Please refresh and try again."},
                status=http_status.HTTP_409_CONFLICT,
            )

        self._log_slot_created(slot, request)
        return response.Response(MaterializedColumnSlotSerializer(slot).data, status=http_status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """Delete a materialized column slot with activity logging."""
        slot = self.get_object()

        # PENDING slots can be safely cancelled (no column has been assigned yet).
        # READY/ERROR slots can be deleted at any time. BACKFILL slots have an in-flight
        # mutation populating their column — wait for it to finish.
        if slot.state == MaterializedColumnSlotState.BACKFILL:
            return response.Response(
                {"error": "Cannot delete slot while backfill is in progress. Wait for completion or failure."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        property_name = slot.property_definition.name

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
        """Re-queue a failed slot for the next weekly backfill cycle.

        Resets the slot to PENDING and clears the previously assigned slot_index so the
        weekly workflow can pack it into the freshest available column. The error_message
        is cleared so the UI no longer flags it as failed.
        """
        slot = self.get_object()

        if slot.state != MaterializedColumnSlotState.ERROR:
            return response.Response(
                {"error": f"Can only retry slots in ERROR state. Current state: {slot.state}"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        property_name = slot.property_definition.name

        slot.state = MaterializedColumnSlotState.PENDING
        slot.slot_index = None
        slot.error_message = None
        slot.backfill_temporal_run_id = None
        slot.save(
            update_fields=[
                "state",
                "slot_index",
                "error_message",
                "backfill_temporal_run_id",
                "updated_at",
            ]
        )

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
                        after="PENDING",
                    ),
                ],
            ),
        )

        return response.Response(MaterializedColumnSlotSerializer(slot).data)
