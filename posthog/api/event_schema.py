from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.schema_property_group import SchemaPropertyGroupSerializer
from posthog.models import EventDefinition, EventSchema, SchemaPropertyGroup


class EventSchemaSerializer(serializers.ModelSerializer):
    property_group = SchemaPropertyGroupSerializer(read_only=True)
    property_group_id = serializers.PrimaryKeyRelatedField(
        queryset=SchemaPropertyGroup.objects.none(), source="property_group", write_only=True
    )

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            team_id = self.context.get("team_id")
            if team_id:
                fields["property_group_id"].queryset = SchemaPropertyGroup.objects.filter(team_id=team_id)  # type: ignore
                fields["event_definition"].queryset = EventDefinition.objects.filter(team_id=team_id)  # type: ignore
        return fields

    class Meta:
        model = EventSchema
        fields = (
            "id",
            "event_definition",
            "property_group",
            "property_group_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "property_group", "created_at", "updated_at")

    def validate(self, attrs):
        event_definition = attrs.get("event_definition")
        property_group = attrs.get("property_group")

        if event_definition and property_group:
            if EventSchema.objects.filter(event_definition=event_definition, property_group=property_group).exists():
                raise serializers.ValidationError(
                    f"Property group '{property_group.name}' is already added to this event schema"
                )

        return attrs

    def create(self, validated_data):
        instance = EventSchema.objects.create(**validated_data)
        return EventSchema.objects.prefetch_related("property_group__properties").get(pk=instance.pk)


class EventSchemaViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    serializer_class = EventSchemaSerializer
    queryset = EventSchema.objects.all()
    lookup_field = "id"

    def _filter_queryset_by_parents_lookups(self, queryset):
        """Override to handle EventSchema which doesn't have a direct team field"""
        parents_query_dict = self.parents_query_dict.copy()

        # Rewrite team/project lookups to use event_definition__team
        if "team_id" in parents_query_dict:
            parents_query_dict["event_definition__team_id"] = parents_query_dict.pop("team_id")
        if "project_id" in parents_query_dict:
            parents_query_dict["event_definition__team__project_id"] = parents_query_dict.pop("project_id")

        if parents_query_dict:
            try:
                return queryset.filter(**parents_query_dict)
            except ValueError:
                from rest_framework.exceptions import NotFound

                raise NotFound()
        else:
            return queryset

    def safely_get_queryset(self, queryset):
        event_definition_id = self.request.query_params.get("event_definition")
        if event_definition_id:
            return (
                queryset.filter(event_definition_id=event_definition_id)
                .select_related("property_group")
                .prefetch_related("property_group__properties")
                .order_by("-created_at")
            )
        return (
            queryset.select_related("property_group")
            .prefetch_related("property_group__properties")
            .order_by("-created_at")
        )
