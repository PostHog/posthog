from typing import Any
from urllib.parse import urlparse

from django.core.cache import cache
from django.views.decorators.debug import sensitive_variables

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.response import Response

from posthog.api.oauth.cimd import _cache_key, validate_cimd_url
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.helpers.impersonation import is_impersonated
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.oauth import (
    CIMDVerificationToken,
    OAuthApplication,
    create_cimd_verification_token,
    normalize_cimd_url,
)
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission


class CIMDVerificationTokenSerializer(serializers.ModelSerializer):
    """Read shape for list/retrieve/create-response. `cimd_url` is nullable here for
    tokens issued before URL binding; the write serializers below require a value."""

    created_by = UserBasicSerializer(read_only=True)
    cimd_url = serializers.CharField(
        max_length=2048,
        read_only=True,
        allow_null=True,
        help_text=(
            "HTTPS URL of the CIMD metadata document this token verifies at. "
            "Null on tokens issued before URL binding; those no longer verify until bound via PATCH or reissued."
        ),
    )

    class Meta:
        model = CIMDVerificationToken
        fields = [
            "id",
            "label",
            "cimd_url",
            "mask_value",
            "created_by",
            "created_at",
            "last_used_at",
        ]
        read_only_fields = [
            "id",
            "label",
            "mask_value",
            "created_by",
            "created_at",
            "last_used_at",
        ]
        # `label` is set here rather than declared as a field: a serializer attribute
        # named `label` shadows DRF's own `Field.label`, which mypy rejects.
        extra_kwargs = {
            "label": {"help_text": "Human-readable name to identify this token later, e.g. 'Production CIMD partner'."}
        }


class _CIMDUrlWriteValidationMixin:
    """Shared write-path validation for `cimd_url` on the create and update serializers.

    Beyond format/safety, this also rejects a URL that normalizes to no path (e.g.
    `https://host//`, whose `//` survives `validate_cimd_url`'s raw shape check but
    collapses to an empty path in `normalize_cimd_url`). Without this, such a URL is
    accepted at issuance and can then never match any fetch URL, since a pathless URL is
    itself rejected as a client_id, so the token would silently never verify.

    Returns the normalized form, which is what gets persisted. `create` would normalize
    anyway inside `create_cimd_verification_token`, but PATCH writes `validated_data`
    straight through, and an unnormalized binding never matches the normalized fetch URL.
    """

    def validate_cimd_url(self, value: str) -> str:
        value = value.strip()
        # Skips the DNS check: the URL is often not serving yet at issuance time,
        # and the fetch path re-validates with SSRF checks before it ever loads it.
        valid, error = validate_cimd_url(value, what="CIMD metadata URL")
        if not valid:
            raise serializers.ValidationError(error)
        try:
            # Accessing .port is what validates it; urlparse itself accepts "host:abc".
            _ = urlparse(value).port
        except ValueError:
            raise serializers.ValidationError("CIMD metadata URL has an invalid port.")
        normalized = normalize_cimd_url(value)
        if not urlparse(normalized).path:
            raise serializers.ValidationError(
                "CIMD metadata URL must include a path component. A URL ending only in "
                "slashes normalizes to no path and could never verify."
            )
        return normalized


class CIMDVerificationTokenCreateSerializer(_CIMDUrlWriteValidationMixin, serializers.ModelSerializer):
    """Write shape for `create`. `cimd_url` is required and non-null: only tokens
    issued before URL binding existed are nullable, not new ones."""

    cimd_url = serializers.CharField(
        max_length=2048,
        required=True,
        allow_null=False,
        help_text=(
            "HTTPS URL of the CIMD metadata document this token will be published in. "
            "The token only verifies at this URL, so a copy hosted anywhere else is rejected. "
            "Host case, an explicit :443 and a trailing slash are normalized away; the path is case-sensitive."
        ),
    )

    class Meta:
        model = CIMDVerificationToken
        fields = ["label", "cimd_url"]
        extra_kwargs = {
            "label": {"help_text": "Human-readable name to identify this token later, e.g. 'Production CIMD partner'."}
        }

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


class CIMDVerificationTokenUpdateSerializer(_CIMDUrlWriteValidationMixin, serializers.ModelSerializer):
    """Write shape for `partial_update` (PATCH). Exposes only `cimd_url`, and only ever
    performs a null -> value transition: `validate` rejects any instance whose `cimd_url`
    is already set, so an existing binding can never be re-pointed through this endpoint.
    """

    cimd_url = serializers.CharField(
        max_length=2048,
        required=True,
        allow_null=False,
        help_text=(
            "HTTPS URL of the CIMD metadata document to bind this token to. Only settable "
            "once, on a token with no existing binding; an already-bound token must be reissued instead."
        ),
    )

    class Meta:
        model = CIMDVerificationToken
        fields = ["cimd_url"]

    def validate(self, attrs: dict[str, str]) -> dict[str, str]:
        if self.instance is not None and self.instance.cimd_url:
            raise serializers.ValidationError(
                {
                    "cimd_url": "This token is already bound to a CIMD URL and cannot be re-pointed here. Reissue the token instead."
                }
            )
        return attrs


@extend_schema(extensions={"x-product": "core"})
class CIMDVerificationTokenViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Manage CIMD verification tokens for an organization.

    A partner embeds the plaintext token in their CIMD metadata document as
    `verification_token` inside the `com.posthog` object (the legacy top-level
    `posthog_verification_token` field still works as a fallback). When PostHog fetches
    the metadata, matching the token links the partner app to this organization and
    grants a higher default rate limit for account provisioning.

    Each token is scoped at creation to the one `cimd_url` it will be published at,
    and verifies nowhere else. Two organizations may name the same URL; only the one
    whose token is actually served there verifies, so claiming a URL cannot be used
    to block a partner from verifying theirs.

    The plaintext value is only available on creation; we store a hash.
    """

    scope_object = "organization"
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission]
    queryset = CIMDVerificationToken.objects.select_related("created_by").order_by("-created_at")
    serializer_class = CIMDVerificationTokenSerializer
    # No PUT: partial_update (PATCH) only ever binds a null cimd_url, which a full
    # replace would make awkward to express safely; the create/reissue flow covers
    # replacing every other field. No TRACE either, PostHog's viewsets don't use it.
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset):
        return queryset.filter(organization_id=self.organization_id)

    def get_serializer_class(self) -> type[serializers.ModelSerializer]:
        if self.action == "create":
            return CIMDVerificationTokenCreateSerializer
        if self.action == "partial_update":
            return CIMDVerificationTokenUpdateSerializer
        return CIMDVerificationTokenSerializer

    @extend_schema(
        request=CIMDVerificationTokenCreateSerializer, responses={201: CIMDVerificationTokenWithValueSerializer}
    )
    @sensitive_variables("plaintext", "output")
    def create(self, request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token, plaintext = create_cimd_verification_token(
            organization=self.organization,
            label=serializer.validated_data["label"],
            cimd_url=serializer.validated_data["cimd_url"],
            created_by=request.user if request.user.is_authenticated else None,
        )
        token.value = plaintext  # type: ignore[attr-defined]
        output = CIMDVerificationTokenWithValueSerializer(token).data
        log_activity(
            organization_id=self.organization.id,
            team_id=None,
            user=request.user if request.user.is_authenticated else None,
            was_impersonated=is_impersonated(request),
            item_id=str(token.id),
            scope="CIMDVerificationToken",
            activity="created",
            detail=Detail(name=token.label),
        )
        return Response(output, status=201)

    @extend_schema(request=CIMDVerificationTokenUpdateSerializer, responses={200: CIMDVerificationTokenSerializer})
    def partial_update(self, request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        instance.refresh_from_db()
        log_activity(
            organization_id=self.organization.id,
            team_id=None,
            user=request.user if request.user.is_authenticated else None,
            was_impersonated=is_impersonated(request),
            item_id=str(instance.id),
            scope="CIMDVerificationToken",
            activity="updated",
            detail=Detail(name=instance.label),
        )
        output = CIMDVerificationTokenSerializer(instance).data
        return Response(output, status=200)

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
        for client_id in OAuthApplication.objects.filter(
            is_cimd_client=True,
            organization_id=org_id,
        ).values_list("client_id", flat=True):
            cache.delete(_cache_key(client_id))

        request = self.request
        log_activity(
            organization_id=org_id,
            team_id=None,
            user=request.user if request.user.is_authenticated else None,
            was_impersonated=is_impersonated(request),
            item_id=token_id,
            scope="CIMDVerificationToken",
            activity="deleted",
            detail=Detail(name=label),
        )
