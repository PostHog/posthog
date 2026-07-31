from typing import Any, cast

import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, request, response, serializers, status
from rest_framework.request import Request
from rest_framework.viewsets import ModelViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.constants import AvailableFeature
from posthog.event_usage import groups
from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.models.organization import Organization
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission
from posthog.security.url_validation import is_url_allowed

from ee.api.scim.utils import disable_scim_for_config, enable_scim_for_config, regenerate_scim_token_for_config


def _capture_idp_config_event(
    request: Request, config: IdentityProviderConfig, event_type: str, properties: dict | None = None
) -> None:
    properties = {**(properties or {}), "identity_provider_config_id": str(config.id)}
    posthoganalytics.capture(
        event=f"organization idp config {event_type}",
        distinct_id=str(request.user.distinct_id),  # type: ignore[union-attr]
        properties=properties,
        groups=groups(config.organization),
    )


class IdentityProviderConfigSerializer(serializers.ModelSerializer):
    scim_bearer_token = serializers.SerializerMethodField(
        help_text="Plaintext SCIM bearer token. Only returned once, immediately after SCIM is enabled or the token is regenerated; null otherwise."
    )
    id_jag_allowed_clients = serializers.ListField(
        child=serializers.CharField(max_length=256),
        required=False,
        allow_empty=True,
        help_text="Allowed ID-JAG client IDs. Empty list allows any client_id.",
    )
    has_saml = serializers.BooleanField(read_only=True, help_text="Whether SAML is fully configured on this config.")
    has_scim = serializers.BooleanField(
        read_only=True, help_text="Whether SCIM is enabled and a bearer token is set on this config."
    )
    has_id_jag = serializers.BooleanField(
        read_only=True, help_text="Whether ID-JAG (XAA) is configured on this config."
    )

    class Meta:
        model = IdentityProviderConfig
        fields = (
            "id",
            "name",
            "created_at",
            "updated_at",
            "has_saml",
            "saml_entity_id",
            "saml_acs_url",
            "saml_x509_cert",
            "has_scim",
            "scim_enabled",
            "scim_bearer_token",
            "has_id_jag",
            "id_jag_issuer_url",
            "id_jag_jwks_url",
            "id_jag_allowed_clients",
        )
        extra_kwargs = {
            "name": {"help_text": "Display name for this IdP configuration (e.g. 'Okta production')."},
            "created_at": {"read_only": True},
            "updated_at": {"read_only": True},
            "saml_entity_id": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
                "help_text": "SAML IdP entity ID (issuer).",
            },
            "saml_acs_url": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
                "help_text": "SAML single sign-on (ACS) URL the IdP redirects to.",
            },
            "saml_x509_cert": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
                "help_text": "SAML IdP X.509 signing certificate (PEM).",
            },
            "scim_enabled": {
                "required": False,
                "help_text": "Whether SCIM provisioning is enabled. Setting this true generates a bearer token (returned once); setting it false clears the token.",
            },
            "id_jag_issuer_url": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
                "help_text": "Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG.",
            },
            "id_jag_jwks_url": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
                "help_text": "Override JWKS URL. Defaults to OIDC discovery on the issuer URL.",
            },
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._scim_plain_token: str | None = None

    @staticmethod
    def _normalize_optional_url(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        return stripped.rstrip("/")

    def _validate_id_jag_url(self, value: str | None) -> str | None:
        normalized = self._normalize_optional_url(value)
        if normalized:
            allowed, reason = is_url_allowed(normalized)
            if not allowed:
                raise serializers.ValidationError(f"URL is not allowed: {reason}")
        return normalized

    def validate_id_jag_issuer_url(self, value: str | None) -> str | None:
        return self._validate_id_jag_url(value)

    def validate_id_jag_jwks_url(self, value: str | None) -> str | None:
        return self._validate_id_jag_url(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        organization: Organization = self.context["view"].organization

        if attrs.get("scim_enabled") is not None and not organization.is_feature_available(AvailableFeature.SCIM):
            raise serializers.ValidationError(
                {"scim_enabled": "SCIM provisioning is not available for this organization."},
                code="feature_not_available",
            )

        if attrs.get("id_jag_issuer_url") and not organization.is_feature_available(
            AvailableFeature.XAA_AUTHENTICATION
        ):
            raise serializers.ValidationError(
                {"id_jag_issuer_url": "XAA (ID-JAG) is not available for this organization."},
                code="feature_not_available",
            )

        return attrs

    def create(self, validated_data: dict[str, Any]) -> IdentityProviderConfig:
        validated_data["organization"] = self.context["view"].organization
        scim_enabled = validated_data.pop("scim_enabled", None)
        validated_data.pop("scim_bearer_token", None)

        instance: IdentityProviderConfig = super().create(validated_data)

        if scim_enabled:
            self._scim_plain_token = enable_scim_for_config(instance)

        return instance

    def update(self, instance: IdentityProviderConfig, validated_data: dict[str, Any]) -> IdentityProviderConfig:
        scim_enabled = validated_data.pop("scim_enabled", None)
        validated_data.pop("scim_bearer_token", None)

        scim_plain_token: str | None = None

        # Generate a new token when enabling SCIM, clear it when disabling.
        if scim_enabled is not None:
            if scim_enabled:
                if not instance.scim_enabled:
                    scim_plain_token = enable_scim_for_config(instance)
            else:
                if instance.scim_enabled:
                    disable_scim_for_config(instance)

        instance = super().update(instance, validated_data)
        self._scim_plain_token = scim_plain_token

        return instance

    def get_scim_bearer_token(self, obj: IdentityProviderConfig) -> str | None:
        return self._scim_plain_token


class SCIMTokenResponseSerializer(serializers.Serializer):
    scim_enabled = serializers.BooleanField(help_text="Whether SCIM is enabled for this config.")
    scim_bearer_token = serializers.CharField(
        help_text="Newly generated plaintext SCIM bearer token. Only returned once."
    )


@extend_schema(extensions={"x-product": "core"})
class IdentityProviderConfigViewSet(TeamAndOrgViewSetMixin, ModelViewSet):
    scope_object = "organization"
    serializer_class = IdentityProviderConfigSerializer
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission]
    queryset = IdentityProviderConfig.objects.order_by("created_at")

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        _capture_idp_config_event(request, instance, "created")
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        res = super().update(request, *args, **kwargs)
        _capture_idp_config_event(request, self.get_object(), "updated", {"fields": sorted(request.data.keys())})
        return res

    @extend_schema(request=None, responses=SCIMTokenResponseSerializer)
    @action(methods=["POST"], detail=True, url_path="scim/token")
    def scim_token(self, request: Request, **kwargs: Any) -> response.Response:
        """Regenerate the SCIM bearer token for this IdP config."""
        config = cast(IdentityProviderConfig, self.get_object())

        if not config.organization.is_feature_available(AvailableFeature.SCIM):
            raise exceptions.PermissionDenied("SCIM is not available for this organization")

        if not config.scim_enabled:
            return response.Response(
                {"detail": "SCIM is not enabled for this config"}, status=status.HTTP_400_BAD_REQUEST
            )

        plain_token = regenerate_scim_token_for_config(config)
        return response.Response({"scim_enabled": True, "scim_bearer_token": plain_token})
