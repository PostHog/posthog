import structlog
from rest_framework import response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition, Team
from posthog.models.property_definition import PropertyType
from posthog.permissions import IsStaffUserOrImpersonating

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
            "backfill_temporal_uuid",
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
        )

        return response.Response(MaterializedColumnSlotSerializer(slot).data, status=201)
