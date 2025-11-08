from typing import cast

from django.utils import timezone

import posthoganalytics
from loginas.utils import is_impersonated_session
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.event_usage import groups
from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, dict_changes_between, log_activity

from ee.models.event_definition import EnterpriseEventDefinition


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
    default_columns = serializers.ListField(child=serializers.CharField(), required=False)

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
            "hidden",
            # Action fields
            "is_action",
            "action_id",
            "is_calculating",
            "last_calculated_at",
            "created_by",
            "post_to_slack",
            "default_columns",
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

    def get_fields(self):
        fields = super().get_fields()
        # Allow name to be writable during creation, read-only during updates
        request = self.context.get("request")
        if request and request.method == "POST":
            fields["name"].read_only = False
        return fields

    def validate(self, data):
        validated_data = super().validate(data)

        if "hidden" in validated_data and "verified" in validated_data:
            if validated_data["hidden"] and validated_data["verified"]:
                raise serializers.ValidationError("An event cannot be both hidden and verified")

        return validated_data

    def create(self, validated_data):
        request = self.context.get("request")
        # Get viewset from context to access organization_id and team_id
        view = self.context.get("view")
        if not view:
            raise serializers.ValidationError("View context is required")
        if not request:
            raise serializers.ValidationError("Request context is required")

        # Type narrowing for mypy
        assert view is not None
        assert request is not None

        # Handle enterprise-specific fields
        if "updated_by" not in validated_data and request.user:
            validated_data["updated_by"] = request.user

        # Set timestamps to None - will be populated when first real event is ingested
        validated_data["team_id"] = view.team_id
        validated_data["project_id"] = view.project_id
        validated_data["created_at"] = None
        validated_data["last_seen_at"] = None

        # Handle verified status
        if validated_data.get("verified", False) and request.user:
            validated_data["verified_by"] = request.user
            validated_data["verified_at"] = timezone.now()
            validated_data["hidden"] = False

        # If hidden is set, ensure verified is false
        if validated_data.get("hidden", False):
            validated_data["verified"] = False
            validated_data["verified_by"] = None
            validated_data["verified_at"] = None

        # Remove fields that don't exist on the model
        validated_data.pop("post_to_slack", None)

        event_definition = super().create(validated_data)

        # Log activity for audit trail
        from posthog.models.utils import UUIDT

        if request.user:
            log_activity(
                organization_id=cast(UUIDT, view.organization_id),
                team_id=view.team_id,
                user=request.user,
                was_impersonated=is_impersonated_session(request),
                item_id=str(event_definition.id),
                scope="EventDefinition",
                activity="created",
                detail=Detail(name=event_definition.name, changes=None),
            )

        return event_definition

    def update(self, event_definition: EnterpriseEventDefinition, validated_data):
        validated_data["updated_by"] = self.context["request"].user

        # If setting hidden=True, ensure verified becomes false
        if validated_data.get("hidden", False):
            validated_data["verified"] = False
            validated_data["verified_by"] = None
            validated_data["verified_at"] = None
        # If setting verified=True, ensure hidden becomes false
        elif validated_data.get("verified", False):
            validated_data["hidden"] = False

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

        verified_old = event_definition.verified
        verified_new = validated_data.get("verified", verified_old)

        # If verified status has changed, track it
        if "verified" in validated_data and verified_old != verified_new:
            user = cast(User, self.context["request"].user)
            posthoganalytics.capture(
                "event verification toggled",
                distinct_id=str(user.distinct_id),
                properties={
                    "verified": verified_new,
                    "event_name": event_definition.name,
                    "is_custom_event": not event_definition.name.startswith("$"),
                },
                groups=groups(user.organization),
            )

        return super().update(event_definition, validated_data)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["owner"] = (
            UserBasicSerializer(instance=instance.owner).data if hasattr(instance, "owner") and instance.owner else None
        )

        # Ensure default_columns is always an array
        if representation.get("default_columns") is None:
            representation["default_columns"] = []

        return representation

    def get_is_action(self, obj):
        return hasattr(obj, "action_id") and obj.action_id is not None
