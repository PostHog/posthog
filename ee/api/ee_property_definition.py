from rest_framework import serializers

from ee.models.property_definition import EnterprisePropertyDefinition
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.models import PropertyDefinition
from posthog.models.activity_logging.activity_log import dict_changes_between, log_activity, Detail


class EnterprisePropertyDefinitionSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    updated_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = EnterprisePropertyDefinition
        fields = (
            "id",
            "name",
            "description",
            "tags",
            "is_numerical",
            "updated_at",
            "updated_by",
            "query_usage_30_day",
            "is_seen_on_filtered_events",
            "property_type",
        )
        read_only_fields = ["id", "name", "is_numerical", "query_usage_30_day", "is_seen_on_filtered_events"]

    def update(self, property_definition: EnterprisePropertyDefinition, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        if "property_type" in validated_data:
            if validated_data["property_type"] == "Numeric":
                validated_data["is_numerical"] = True
            else:
                validated_data["is_numerical"] = False

        before_state = {
            k: property_definition.__dict__[k] for k in validated_data.keys() if k in property_definition.__dict__
        }
        # KLUDGE: if we get a None value for tags, and we're not adding any
        # then we get an activity log that we went from null to the empty array ¯\_(ツ)_/¯
        if "tags" not in before_state or before_state["tags"] is None:
            before_state["tags"] = []

        changes = dict_changes_between("PropertyDefinition", before_state, validated_data, True)

        log_activity(
            organization_id=None,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            item_id=str(property_definition.id),
            scope="PropertyDefinition",
            activity="changed",
            detail=Detail(
                name=str(property_definition.name),
                type=PropertyDefinition.Type(property_definition.type).label,
                changes=changes,
            ),
        )

        return super().update(property_definition, validated_data)
