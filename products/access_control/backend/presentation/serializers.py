"""
DRF serializers for access_control.

These convert DTOs <-> JSON and validate incoming request bodies.
They must never touch ORM models directly — presentation code only
talks to the facade.
"""

from rest_framework import serializers

from ..facade import contracts
from ..facade.contracts import PropertyAccessLevel

_ACCESS_LEVEL_CHOICES = [(e.value, e.value) for e in PropertyAccessLevel]


class PropertyAccessControlRuleSerializer(serializers.Serializer):
    """Serializes a single access control rule DTO."""

    id = serializers.UUIDField(read_only=True)
    access_level = serializers.ChoiceField(
        choices=_ACCESS_LEVEL_CHOICES,
        help_text="The access level for this rule.",
    )
    organization_member = serializers.UUIDField(
        source="organization_member_id",
        allow_null=True,
        help_text="The organization member UUID this rule applies to, if any.",
    )
    role = serializers.UUIDField(
        source="role_id",
        allow_null=True,
        help_text="The role UUID this rule applies to, if any.",
    )
    created_by = serializers.IntegerField(
        source="created_by_id",
        allow_null=True,
        read_only=True,
    )
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: contracts.PropertyAccessControlRule) -> dict:
        data = super().to_representation(instance)
        # Serializer would otherwise coerce the enum via its str() (fine),
        # but we normalize explicitly to the enum value string.
        data["access_level"] = instance.access_level.value
        return data


class PropertyAccessControlStateSerializer(serializers.Serializer):
    """Serializes the aggregate state for a property definition.

    Preserves the existing API shape: ``access_controls`` is the list
    of rules, plus the available levels and the computed default.
    """

    access_controls = PropertyAccessControlRuleSerializer(
        source="rules",
        many=True,
        help_text="List of all access control rules for this property definition.",
    )
    available_access_levels = serializers.ListField(
        child=serializers.CharField(),
        help_text="Available access levels that can be assigned.",
    )
    default_access_level = serializers.CharField(
        help_text="The default access level when no rules match.",
    )

    def to_representation(self, instance: contracts.PropertyAccessControlState) -> dict:
        return {
            "access_controls": PropertyAccessControlRuleSerializer(instance.rules, many=True).data,
            "available_access_levels": [level.value for level in instance.available_access_levels],
            "default_access_level": instance.default_access_level.value,
        }


class PropertyAccessControlUpdateSerializer(serializers.Serializer):
    """Request body for upserting a rule (create or update)."""

    property_definition_id = serializers.CharField(
        help_text="The property definition ID this rule applies to.",
    )
    access_level = serializers.ChoiceField(
        choices=_ACCESS_LEVEL_CHOICES,
        help_text="The access level to set for this rule.",
    )
    organization_member = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="The organization member UUID to set an override for.",
    )
    role = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="The role UUID to set an override for.",
    )


class PropertyAccessControlDeleteSerializer(serializers.Serializer):
    """Query parameters for deleting a rule.

    Identifies the rule by ``property_definition_id`` plus an optional
    ``organization_member`` or ``role`` override target. Omitting both
    targets deletes the default rule for the property definition.
    """

    property_definition_id = serializers.CharField(
        help_text="The property definition ID the rule applies to.",
    )
    organization_member = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="The organization member UUID whose override should be deleted.",
    )
    role = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="The role UUID whose override should be deleted.",
    )
