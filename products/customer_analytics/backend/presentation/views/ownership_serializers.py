"""
Response serializers for the ``ownership`` block on the external account routes. Kept apart from
``external.py`` because ``account_actions.py`` renders the single-account body by hand and needs
the same shape without importing the views.
"""

from rest_framework import serializers

from products.customer_analytics.backend.facade.enums import OwnershipRoleDiagnostic, OwnershipRoleState


class ExternalAccountOwnershipHolderSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="PostHog user id of the holder.")
    email = serializers.CharField(
        allow_null=True, help_text="Current email address of the holder; null for a holder outside the organization."
    )
    name = serializers.CharField(
        allow_null=True, help_text="Current display name of the holder; null when unset or outside the organization."
    )
    is_organization_member = serializers.BooleanField(
        help_text="Whether the holder is currently a member of the project's organization."
    )
    is_active = serializers.BooleanField(help_text="Whether the holder's PostHog user account is active.")


class ExternalAccountRoleOwnershipSerializer(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=OwnershipRoleState.choices,
        help_text=(
            "`unmanaged`: customer analytics does not hold authority over this role on this account; "
            "the holder, if any, is a legacy assignment. `assigned`: the holder is authoritative. "
            "`cleared`: the role is authoritatively empty. `blocked`: the role is managed but its holder "
            "cannot be projected; see `diagnostics` and keep the last applied value."
        ),
    )
    definition_id = serializers.UUIDField(
        allow_null=True, help_text="Relationship definition bound to this role for the project, or null."
    )
    controlled_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When customer analytics last decided this role on this account; null while unmanaged.",
    )
    relationship_id = serializers.UUIDField(
        allow_null=True, help_text="The active relationship holding the role, or null when empty."
    )
    holder = ExternalAccountOwnershipHolderSerializer(allow_null=True, help_text="The current holder, or null.")
    diagnostics = serializers.ListField(
        child=serializers.ChoiceField(choices=OwnershipRoleDiagnostic.choices),
        help_text="Why a managed role is blocked. Informational on an unmanaged role.",
    )


class ExternalAccountOwnershipSerializer(serializers.Serializer):
    account_id = serializers.CharField(help_text="Account UUID, the canonical identity within this project.")
    external_id = serializers.CharField(
        allow_null=True, help_text="External account key: the PostHog organization id the account is linked to."
    )
    region = serializers.CharField(
        allow_null=True, help_text="Region of this PostHog instance (`us`, `eu`), or null when self-hosted."
    )
    ae = ExternalAccountRoleOwnershipSerializer(help_text="The account executive role.")
    csm = ExternalAccountRoleOwnershipSerializer(help_text="The customer success manager role.")
