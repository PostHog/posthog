from typing import Any

from rest_framework import mixins, serializers, viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.oauth import CIMDVerificationToken, create_cimd_verification_token
from posthog.permissions import OrganizationAdminWritePermissions


class CIMDVerificationTokenSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    value = serializers.CharField(read_only=True, help_text="Plaintext token, only returned on creation")

    class Meta:
        model = CIMDVerificationToken
        fields = [
            "id",
            "label",
            "mask_value",
            "created_by",
            "created_at",
            "last_used_at",
            "value",
        ]
        read_only_fields = [
            "id",
            "mask_value",
            "created_by",
            "created_at",
            "last_used_at",
            "value",
        ]

    def validate_label(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Label cannot be empty.")
        return value


class CIMDVerificationTokenViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Manage CIMD verification tokens for an organization.

    A partner embeds the plaintext token in their CIMD metadata document under
    `posthog_verification_token`. When PostHog fetches the metadata, matching
    the token links the partner app to this organization and grants a higher
    default rate limit for account provisioning.

    The plaintext value is only available on creation; we store a hash.
    """

    scope_object = "organization"
    permission_classes = [OrganizationAdminWritePermissions]
    queryset = CIMDVerificationToken.objects.select_related("created_by").order_by("-created_at")
    serializer_class = CIMDVerificationTokenSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(organization_id=self.organization_id)

    def create(self, request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token, plaintext = create_cimd_verification_token(
            organization=self.organization,
            label=serializer.validated_data["label"],
            created_by=request.user if request.user.is_authenticated else None,
        )
        output = self.get_serializer(token).data
        output["value"] = plaintext
        return Response(output, status=201)
