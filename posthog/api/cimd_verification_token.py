from typing import Any

from django.core.cache import cache
from django.views.decorators.debug import sensitive_variables

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.oauth import CIMDVerificationToken, OAuthApplication, create_cimd_verification_token
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission


class CIMDVerificationTokenSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = CIMDVerificationToken
        fields = [
            "id",
            "label",
            "mask_value",
            "created_by",
            "created_at",
            "last_used_at",
        ]
        read_only_fields = [
            "id",
            "mask_value",
            "created_by",
            "created_at",
            "last_used_at",
        ]

    def validate_label(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Label cannot be empty.")
        return value


class CIMDVerificationTokenWithValueSerializer(CIMDVerificationTokenSerializer):
    """Create-response variant that includes the plaintext token.

    Only emitted from the create endpoint - storage-side we only persist the
    hash, so subsequent reads use the base serializer.
    """

    value = serializers.CharField(read_only=True, help_text="Plaintext token, only returned on creation")

    class Meta(CIMDVerificationTokenSerializer.Meta):
        fields = [*CIMDVerificationTokenSerializer.Meta.fields, "value"]
        read_only_fields = [*CIMDVerificationTokenSerializer.Meta.read_only_fields, "value"]


@extend_schema(tags=["core"])
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
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission]
    queryset = CIMDVerificationToken.objects.select_related("created_by").order_by("-created_at")
    serializer_class = CIMDVerificationTokenSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(organization_id=self.organization_id)

    @extend_schema(responses={201: CIMDVerificationTokenWithValueSerializer})
    @sensitive_variables("plaintext", "output")
    def create(self, request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token, plaintext = create_cimd_verification_token(
            organization=self.organization,
            label=serializer.validated_data["label"],
            created_by=request.user if request.user.is_authenticated else None,
        )
        token.value = plaintext  # type: ignore[attr-defined]
        output = CIMDVerificationTokenWithValueSerializer(token).data
        log_activity(
            organization_id=self.organization.id,
            team_id=None,
            user=request.user if request.user.is_authenticated else None,
            was_impersonated=getattr(request, "impersonated_session", False),
            item_id=str(token.id),
            scope="CIMDVerificationToken",
            activity="created",
            detail=Detail(name=token.label),
        )
        return Response(output, status=201)

    def perform_destroy(self, instance: CIMDVerificationToken) -> None:
        org_id = instance.organization_id
        label = instance.label
        token_id = str(instance.id)
        instance.delete()

        # Force metadata re-fetch for CIMD partner apps linked to this org so
        # verification is re-evaluated on the next request. If another token on
        # this org still matches the metadata, the app stays linked; otherwise
        # it drops back to the unverified tier on next fetch. This matches the
        # revoke-confirm UX ("partners using this token will no longer be
        # recognized") without touching apps that have a different linking
        # token.
        from posthog.api.oauth.cimd import _cache_key

        for url in OAuthApplication.objects.filter(
            is_cimd_client=True,
            organization_id=org_id,
            cimd_metadata_url__isnull=False,
        ).values_list("cimd_metadata_url", flat=True):
            if url:
                cache.delete(_cache_key(url))

        request = self.request
        log_activity(
            organization_id=org_id,
            team_id=None,
            user=request.user if request.user.is_authenticated else None,
            was_impersonated=getattr(request, "impersonated_session", False),
            item_id=token_id,
            scope="CIMDVerificationToken",
            activity="deleted",
            detail=Detail(name=label),
        )
