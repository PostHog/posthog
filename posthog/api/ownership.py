from typing import cast

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from posthog.models import OrganizationMembership, User


class TransferOwnershipSerializer(serializers.Serializer):
    user_uuid = serializers.UUIDField(
        required=False,
        help_text="New owner's user UUID. Defaults to yourself. Assigning another member requires organization admin access.",
    )

    def resolve_owner(self) -> User:
        requester = cast(User, self.context["request"].user)
        user_uuid = self.validated_data.get("user_uuid", requester.uuid)
        organization = self.context["get_organization"]()
        if (
            user_uuid != requester.uuid
            and not OrganizationMembership.objects.filter(
                organization=organization, user=requester, level__gte=OrganizationMembership.Level.ADMIN
            ).exists()
        ):
            raise PermissionDenied("Only organization admins can transfer ownership to another member.")
        owner = User.objects.filter(
            uuid=user_uuid, is_active=True, organization_membership__organization=organization
        ).first()
        if owner is None:
            raise serializers.ValidationError({"user_uuid": "Choose an active member of this organization."})
        return owner
