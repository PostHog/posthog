from django.utils import timezone
from rest_framework import serializers

from ee.models.event_definition import EnterpriseEventDefinition
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.models.activity_logging.activity_log import (
    dict_changes_between,
    log_activity,
    Detail,
)

from loginas.utils import is_impersonated_session


class EnterpriseEventDefinitionSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    updated_by = UserBasicSerializer(read_only=True)
    verified_by = UserBasicSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    is_action = serializers.SerializerMethodField(read_only=True)
    action_id = serializers.IntegerField(read_only=True)
    is_calculating = serializers.BooleanField(read_only=True)
    last_calculated_at = serializers.DateTimeField(read_only=True)
    last_updated_at = serializers.DateTimeField(read_only=True)
    post_to_slack = serializers.BooleanField(default=False)

    class Meta:
        model = EnterpriseEventDefinition
        fields = (
            "id",
            "name",
            "owner",
            "description",
            "tags",
            "created_at",
            "updated_at",
            "updated_by",
            "last_seen_at",
            "last_updated_at",
            "verified",
            "verified_at",
            "verified_by",
            # Action fields
            "is_action",
            "action_id",
            "is_calculating",
            "last_calculated_at",
            "created_by",
            "post_to_slack",
        )
        read_only_fields = [
            "id",
            "name",
            "created_at",
            "updated_at",
            "last_seen_at",
            "last_updated_at",
            "verified_at",
            "verified_by",
            # Action fields
            "is_action",
            "action_id",
            "is_calculating",
            "last_calculated_at",
            "created_by",
        ]

    def update(self, event_definition: EnterpriseEventDefinition, validated_data):
        validated_data["updated_by"] = self.context["request"].user

        if "verified" in validated_data:
            if validated_data["verified"] and not event_definition.verified:
                # Verify event only if previously unverified
                validated_data["verified_by"] = self.context["request"].user
                validated_data["verified_at"] = timezone.now()
                validated_data["verified"] = True
            elif not validated_data["verified"]:
                # Unverifying event nullifies verified properties
                validated_data["verified_by"] = None
                validated_data["verified_at"] = None
                validated_data["verified"] = False
            else:
                # Attempting to re-verify an already verified event, invalid action. Ignore attribute.
                validated_data.pop("verified")

        before_state = {
            k: event_definition.__dict__[k] for k in validated_data.keys() if k in event_definition.__dict__
        }
        # KLUDGE: if we get a None value for tags, and we're not adding any
        # then we get an activity log that we went from null to the empty array ¯\_(ツ)_/¯
        if "tags" not in before_state or before_state["tags"] is None:
            before_state["tags"] = []

        changes = dict_changes_between("EventDefinition", before_state, validated_data, True)

        log_activity(
            organization_id=None,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            item_id=str(event_definition.id),
            scope="EventDefinition",
            activity="changed",
            was_impersonated=is_impersonated_session(self.context["request"]),
            detail=Detail(name=str(event_definition.name), changes=changes),
        )

        return super().update(event_definition, validated_data)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["owner"] = (
            UserBasicSerializer(instance=instance.owner).data if hasattr(instance, "owner") and instance.owner else None
        )
        return representation

    def get_is_action(self, obj):
        return hasattr(obj, "action_id") and obj.action_id is not None
