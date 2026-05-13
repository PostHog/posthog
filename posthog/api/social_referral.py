from typing import Any, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field, extend_schema_view
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import SocialReferral
from posthog.models.user import User


@extend_schema_field(OpenApiTypes.OBJECT)
class SocialReferralRefereeStateField(serializers.JSONField):
    """OpenAPI object shape for per-invited-org referral tracking state."""


class SocialReferralSerializer(serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(read_only=True)
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    referee_state = SocialReferralRefereeStateField(
        required=False,
        help_text='Map of invited organization UUID (string) to `{"first_event_sent": boolean}`.',
    )

    class Meta:
        model = SocialReferral
        fields = [
            "id",
            "organization",
            "user",
            "referee_state",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "organization",
            "user",
            "created_at",
        ]

    def validate_referee_state(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise serializers.ValidationError("referee_state must be an object.")
        return value


# TODO(permissioning): Decide creator-only vs org-wide visibility; personal API keys / OAuth scopes;
# internal/system updates to `referee_state` without an end-user principal.
@extend_schema_view(
    list=extend_schema(summary="List social referrals"),
    create=extend_schema(summary="Create social referral"),
    retrieve=extend_schema(summary="Retrieve social referral"),
    update=extend_schema(summary="Update social referral"),
    partial_update=extend_schema(summary="Partially update social referral"),
    destroy=extend_schema(summary="Delete social referral"),
)
@extend_schema(tags=["core"])
class SocialReferralViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for referral share links under an organization."""

    scope_object = "organization"
    queryset = SocialReferral.objects.all()
    serializer_class = SocialReferralSerializer
    # TODO(permissioning): Add explicit permission classes beyond TeamAndOrgViewSetMixin defaults; align with API scopes / AccessControl.
    permission_classes = []

    def safely_get_queryset(self, queryset):
        user = cast(User, self.request.user)
        return queryset.filter(organization_id=self.organization_id, user_id=user.id)

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(organization_id=self.organization_id, user=self.request.user)
