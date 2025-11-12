from django.utils import timezone

import posthoganalytics
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.event_usage import groups

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

    def get_extra_kwargs(self):
        extra_kwargs = super().get_extra_kwargs()

        # Allow name to be writable during creation, read-only during updates
        if self.instance is None:  # Creation
            extra_kwargs["name"] = {"read_only": False}

        return extra_kwargs

    def _apply_verified_hidden_rules(self, validated_data, user, existing_verified=False):
        """
        Apply verified/hidden mutual exclusion rules.

        Args:
            validated_data: The data being validated
            user: The user making the change
            existing_verified: For updates, whether the instance is currently verified
        """
        if validated_data.get("hidden", False):
            # Setting hidden=True forces verified=False
            validated_data["verified"] = False
            validated_data["verified_by"] = None
            validated_data["verified_at"] = None
        elif validated_data.get("verified", False):
            # Only set verified metadata if transitioning from unverified to verified
            if not existing_verified:
                validated_data["verified_by"] = user
                validated_data["verified_at"] = timezone.now()
                validated_data["hidden"] = False
            # If already verified, this is a no-op (for updates only)
            elif existing_verified and self.instance is not None:
                validated_data.pop("verified")
        elif "verified" in validated_data and not validated_data["verified"]:
            # Explicitly unverifying - nullify verified properties
            validated_data["verified_by"] = None
            validated_data["verified_at"] = None

    def validate(self, data):
        validated_data = super().validate(data)

        # Validate that hidden and verified are mutually exclusive when both provided
        if "hidden" in validated_data and "verified" in validated_data:
            if validated_data["hidden"] and validated_data["verified"]:
                raise serializers.ValidationError("An event cannot be both hidden and verified")

        # Apply verified/hidden rules for creation
        if self.instance is None:
            user = self.context["request"].user
            self._apply_verified_hidden_rules(validated_data, user, existing_verified=False)

        # Remove post_to_slack field - it exists on Action model but not EventDefinition
        validated_data.pop("post_to_slack", None)

        return validated_data

    def update(self, event_definition: EnterpriseEventDefinition, validated_data):
        """Handle update-specific logic for verified/hidden state transitions."""
        user = self.context["request"].user

        # Apply verified/hidden rules with awareness of current state
        self._apply_verified_hidden_rules(validated_data, user, existing_verified=event_definition.verified)

        # Track verification toggle for analytics
        if "verified" in validated_data:
            verified_old = event_definition.verified
            verified_new = validated_data.get("verified", verified_old)
            if verified_old != verified_new:
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
