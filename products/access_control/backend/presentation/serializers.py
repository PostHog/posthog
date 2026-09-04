"""
DRF serializers for access_control.

These convert DTOs <-> JSON and validate incoming request bodies.
They must never touch ORM models directly — presentation code only
talks to the facade.
"""

from rest_framework import serializers

from posthog.models.organization import OrganizationMembership

from ..facade import contracts
from ..facade.contracts import PropertyAccessLevel
from .access_control import ResolvedAccessSerializer

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


class SubjectAccessEntrySerializer(serializers.Serializer):
    """One subject's access to one scope (the project, or a whole resource type): what is stored,
    what is enforced, and where the enforced level comes from."""

    access_level = serializers.CharField(
        allow_null=True,
        help_text="The subject's own stored rule for this scope. Null when the subject has no rule of its own here.",
    )
    effective_access_level = serializers.CharField(
        allow_null=True,
        help_text="The level that is enforced for the subject after defaults, roles and bypasses are resolved. "
        "Null when nothing resolves, for example a resource the organization is not entitled to.",
    )
    inherited_access = ResolvedAccessSerializer(
        allow_null=True,
        help_text="The level the subject falls back to without a rule of its own, with the rule that supplies it. "
        "Read `source` and `source_subject` to tell a role rule from the project default or an org-admin bypass.",
    )
    minimum = serializers.CharField(help_text="The lowest level this scope allows.")
    maximum = serializers.CharField(help_text="The highest level this scope allows.")


class AccessControlMemberUserSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(help_text="The user's UUID.")
    first_name = serializers.CharField(help_text="The user's first name.")
    last_name = serializers.CharField(help_text="The user's last name.")
    email = serializers.EmailField(help_text="The user's email.")


class AccessControlMemberAccessSerializer(serializers.Serializer):
    """A member's resolved access to the project and to every resource type in it."""

    organization_membership_id = serializers.UUIDField(
        help_text="The organization membership id. Use it as `member_id` on the member rule endpoints.",
    )
    user = AccessControlMemberUserSerializer(help_text="The member's identity.")
    organization_level = serializers.ChoiceField(
        choices=OrganizationMembership.Level.choices,
        help_text="The member's organization level: 1 member, 8 admin, 15 owner. Admins and owners bypass every rule.",
    )
    project = SubjectAccessEntrySerializer(help_text="Access to the project itself.")
    resources = serializers.DictField(
        child=SubjectAccessEntrySerializer(),
        help_text="Access per resource type, keyed by resource name (for example `dashboard`, `feature_flag`).",
    )


class AccessControlRoleAccessSerializer(serializers.Serializer):
    """A role's resolved access to the project and to every resource type in it."""

    role_id = serializers.UUIDField(help_text="The role id. Use it as `role_id` on the role rule endpoints.")
    role_name = serializers.CharField(help_text="The role's name.")
    project = SubjectAccessEntrySerializer(help_text="Access to the project itself.")
    resources = serializers.DictField(
        child=SubjectAccessEntrySerializer(),
        help_text="Access per resource type, keyed by resource name (for example `dashboard`, `feature_flag`).",
    )


class _AccessControlSettingsResponseSerializer(serializers.Serializer):
    available_project_levels = serializers.ListField(
        child=serializers.CharField(),
        help_text="The project access levels, lowest first.",
    )
    available_resource_levels = serializers.ListField(
        child=serializers.CharField(),
        help_text="The resource access levels, lowest first.",
    )
    can_edit = serializers.BooleanField(help_text="Whether the caller may change access rules in this project.")


class AccessControlMembersResponseSerializer(_AccessControlSettingsResponseSerializer):
    results = AccessControlMemberAccessSerializer(many=True, help_text="One entry per organization member.")


class AccessControlRolesResponseSerializer(_AccessControlSettingsResponseSerializer):
    results = AccessControlRoleAccessSerializer(many=True, help_text="One entry per role in the organization.")


class AccessControlResourceDefaultSerializer(serializers.Serializer):
    access_level = serializers.CharField(
        allow_null=True,
        help_text="The stored default level for this resource type. Null when the built-in default applies.",
    )
    minimum = serializers.CharField(help_text="The lowest level this resource type allows.")
    maximum = serializers.CharField(help_text="The highest level this resource type allows.")


class AccessControlObjectRuleResourceSerializer(serializers.Serializer):
    resource = serializers.CharField(help_text="A resource type that supports rules on single objects.")
    available_access_levels = serializers.ListField(
        child=serializers.CharField(),
        help_text="The levels an object rule on this resource type accepts, lowest first.",
    )
    minimum_access_level = serializers.CharField(help_text="The lowest level an object rule on this resource can set.")


class AccessControlDefaultsResponseSerializer(_AccessControlSettingsResponseSerializer):
    """The project's defaults: what everyone without a rule of their own gets."""

    project_access_level = serializers.CharField(help_text="The default project access level for members.")
    resource_access_levels = serializers.DictField(
        child=AccessControlResourceDefaultSerializer(),
        help_text="The default level per resource type, keyed by resource name.",
    )
    object_rule_resources = AccessControlObjectRuleResourceSerializer(
        many=True,
        help_text="The resource types that accept rules on single objects, with the levels each accepts.",
    )


class AccessControlObjectRuleSerializer(serializers.Serializer):
    """A stored rule on one object, as configured for a subject."""

    resource = serializers.CharField(help_text="The object's resource type, for example `dashboard`.")
    resource_id = serializers.CharField(help_text="The object's primary key.")
    name = serializers.CharField(help_text="The object's display name. Falls back to the id when it has no name.")
    short_id = serializers.CharField(
        allow_null=True,
        help_text="The object's short id, for models that link by one (insights, notebooks).",
    )
    access_level = serializers.CharField(help_text="The level the rule grants or restricts to.")


class AccessControlObjectRulesResponseSerializer(serializers.Serializer):
    results = AccessControlObjectRuleSerializer(
        many=True, help_text="The subject's object rules, sorted by resource and name."
    )


class AccessControlPropertyRuleSerializer(serializers.Serializer):
    """A stored rule on one property definition, as configured for a subject."""

    property_definition_id = serializers.UUIDField(help_text="The property definition id.")
    property = serializers.CharField(help_text="The property name.")
    property_type = serializers.CharField(help_text="Whether the property is a `person` or an `event` property.")
    access_level = serializers.CharField(help_text="The rule's level: `none`, `read` or `read_write`.")


class AccessControlPropertyRulesResponseSerializer(serializers.Serializer):
    results = AccessControlPropertyRuleSerializer(
        many=True, help_text="The subject's property rules, sorted by property type and name."
    )
