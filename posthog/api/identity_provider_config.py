from typing import Any, cast

from django.db import transaction
from django.db.models import Q

import posthoganalytics
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import exceptions, request, response, serializers, status
from rest_framework.request import Request
from rest_framework.viewsets import ModelViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scim_request_log import (
    PaginatedSCIMRequestLogSerializer,
    SCIMRequestLogQuerySerializer,
    paginated_scim_request_logs_response,
)
from posthog.api.scoped_related_fields import OrgScopedPrimaryKeyRelatedField
from posthog.api.utils import action
from posthog.constants import AvailableFeature
from posthog.event_usage import groups
from posthog.models.identity_provider_config import ConfigScope, DomainScope, IdentityProviderConfig, saml_configured_q
from posthog.models.linked_identity_provider_config import LinkedIdentityProviderConfig
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission
from posthog.security.url_validation import is_url_allowed

from ee.api.scim.utils import (
    disable_scim_for_config,
    enable_scim_for_config,
    get_scim_base_url,
    regenerate_scim_token_for_config,
)
from ee.models.scim_request_log import SCIMRequestLog


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


class _OrgScopedOrganizationDomainField(OrgScopedPrimaryKeyRelatedField):
    scope_field = "organization"


class IdentityProviderConfigSerializer(serializers.ModelSerializer):
    saml_relay_state = serializers.CharField(
        read_only=True,
        help_text="Stable UUID sent as SAML RelayState to route authentication responses to this IdP configuration.",
    )
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
    has_oidc = serializers.BooleanField(
        read_only=True, help_text="Whether OIDC has an issuer, client ID, and client secret."
    )
    has_oidc_client_secret = serializers.BooleanField(
        read_only=True, help_text="Whether an encrypted OIDC client secret is saved."
    )
    oidc_client_secret = serializers.CharField(
        required=False,
        write_only=True,
        allow_blank=True,
        max_length=4096,
        trim_whitespace=False,
        help_text="OIDC client secret. Omit to keep the saved secret. Set to an empty string to remove it. Never returned in responses.",
    )
    has_scim = serializers.BooleanField(
        read_only=True, help_text="Whether SCIM is enabled and a bearer token is set on this config."
    )
    scim_base_url = serializers.SerializerMethodField(
        help_text="SCIM base URL for this identity provider configuration."
    )
    has_id_jag = serializers.BooleanField(
        read_only=True, help_text="Whether ID-JAG (XAA) is configured on this config."
    )
    organization_domain_ids = _OrgScopedOrganizationDomainField(
        source="organization_domains",
        many=True,
        queryset=OrganizationDomain.objects.all(),
        required=False,
        help_text="Organization domain IDs that this identity provider configuration applies to.",
    )

    class Meta:
        model = IdentityProviderConfig
        fields = (
            "id",
            "name",
            "domain_scope",
            "config_scope",
            "organization_domain_ids",
            "created_at",
            "updated_at",
            "has_saml",
            "has_oidc",
            "has_oidc_client_secret",
            "oidc_issuer_url",
            "oidc_client_id",
            "oidc_client_secret",
            "saml_relay_state",
            "saml_entity_id",
            "saml_acs_url",
            "saml_x509_cert",
            "has_scim",
            "scim_enabled",
            "scim_base_url",
            "scim_bearer_token",
            "has_id_jag",
            "id_jag_issuer_url",
            "id_jag_jwks_url",
            "id_jag_allowed_clients",
        )
        extra_kwargs = {
            "oidc_issuer_url": {
                "help_text": "HTTPS issuer URL. Must exactly match the issuer in the OIDC discovery document."
            },
            "oidc_client_id": {"help_text": "Client ID of the organization's OIDC application."},
            "name": {"help_text": "Display name for this IdP configuration (e.g. 'Okta production')."},
            "domain_scope": {
                "required": False,
                "allow_null": True,
                "help_text": "Domains this configuration applies to. An unset value behaves like selected domains.",
            },
            "config_scope": {
                "required": False,
                "allow_null": True,
                "help_text": "Feature configured by this identity provider configuration.",
            },
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

    def validate_oidc_issuer_url(self, value: str) -> str:
        from urllib.parse import urlsplit

        normalized = value.strip()
        if normalized:
            parsed = urlsplit(normalized)
            if parsed.scheme != "https" or parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise serializers.ValidationError(
                    "Use an HTTPS issuer URL without credentials, a query, or a fragment."
                )
            allowed, reason = is_url_allowed(normalized)
            if not allowed:
                raise serializers.ValidationError(f"URL is not allowed: {reason}")
        return normalized

    def validate_id_jag_jwks_url(self, value: str | None) -> str | None:
        return self._validate_id_jag_url(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        organization: Organization = self.context["view"].organization

        if any(attrs.get(field) for field in ("oidc_issuer_url", "oidc_client_id", "oidc_client_secret")):
            if not organization.is_feature_available(AvailableFeature.OIDC):
                raise serializers.ValidationError(
                    {"oidc_issuer_url": "OIDC is not available for this organization."}, code="feature_not_available"
                )
            if attrs.get("config_scope", getattr(self.instance, "config_scope", None)) != ConfigScope.OIDC:
                raise serializers.ValidationError({"config_scope": "Use an OIDC configuration for OIDC settings."})

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

        instance = cast(IdentityProviderConfig | None, self.instance)
        is_oidc = attrs.get("config_scope", getattr(instance, "config_scope", None)) == ConfigScope.OIDC
        config_fields = (
            ("oidc_issuer_url", "oidc_client_id") if is_oidc else ("saml_entity_id", "saml_acs_url", "saml_x509_cert")
        )
        if not all(attrs.get(field, getattr(instance, field, None)) for field in config_fields):
            return attrs
        if is_oidc and not attrs.get(
            "oidc_client_secret", ((instance.oidc_credentials or {}) if instance else {}).get("client_secret")
        ):
            return attrs

        organization_domains = attrs.get("organization_domains")
        if organization_domains is None:
            proposed_domain_ids = set(
                (instance.organization_domains if instance else OrganizationDomain.objects.none())
                .filter(verified_at__isnull=False)
                .values_list("id", flat=True)
            )
        else:
            proposed_domain_ids = {domain.id for domain in organization_domains if domain.verified_at is not None}

        domain_scope = attrs.get("domain_scope", getattr(instance, "domain_scope", None))
        if is_oidc:
            configured_ids = [
                config.id
                for config in IdentityProviderConfig.objects.filter(
                    organization=organization, config_scope=ConfigScope.OIDC
                )
                if config.has_oidc
            ]
            other_auth_configs = IdentityProviderConfig.objects.filter(organization=organization, id__in=configured_ids)
        else:
            other_auth_configs = IdentityProviderConfig.objects.filter(
                saml_configured_q(), organization=organization
            ).filter(Q(config_scope=ConfigScope.SAML) | Q(config_scope__isnull=True))
        if instance:
            other_auth_configs = other_auth_configs.exclude(pk=instance.pk)

        if domain_scope == DomainScope.ALL:
            has_overlap = other_auth_configs.filter(
                Q(organization__domains__verified_at__isnull=False)
                | Q(linked_identity_provider_configs__organization_domain__verified_at__isnull=False)
            ).exists()
        elif proposed_domain_ids:
            has_overlap = other_auth_configs.filter(
                Q(
                    domain_scope=DomainScope.ALL,
                    organization__domains__id__in=proposed_domain_ids,
                    organization__domains__verified_at__isnull=False,
                )
                | Q(
                    linked_identity_provider_configs__organization_domain_id__in=proposed_domain_ids,
                    linked_identity_provider_configs__organization_domain__verified_at__isnull=False,
                )
            ).exists()
        else:
            has_overlap = False

        if has_overlap:
            protocol = "OIDC" if is_oidc else "SAML"
            raise serializers.ValidationError(
                {
                    "domain_scope": f"This {protocol} configuration overlaps with another {protocol} configuration on one or more verified domains. Choose different domains before saving."
                }
            )

        return attrs

    @staticmethod
    def _sync_organization_domains(
        instance: IdentityProviderConfig, organization_domains: list[OrganizationDomain]
    ) -> None:
        LinkedIdentityProviderConfig.objects.filter(identity_provider_config=instance).delete()
        LinkedIdentityProviderConfig.objects.bulk_create(
            [
                LinkedIdentityProviderConfig(
                    identity_provider_config=instance,
                    organization_domain=organization_domain,
                )
                for organization_domain in organization_domains
            ]
        )

    @transaction.atomic
    def create(self, validated_data: dict[str, Any]) -> IdentityProviderConfig:
        validated_data["organization"] = self.context["view"].organization
        if "oidc_client_secret" in validated_data:
            validated_data["oidc_credentials"] = {"client_secret": validated_data.pop("oidc_client_secret")}
        scim_enabled = validated_data.pop("scim_enabled", None)
        organization_domains = validated_data.pop("organization_domains", [])
        validated_data.pop("scim_bearer_token", None)

        instance: IdentityProviderConfig = super().create(validated_data)
        self._sync_organization_domains(instance, organization_domains)

        if scim_enabled:
            self._scim_plain_token = enable_scim_for_config(instance)

        return instance

    @transaction.atomic
    def update(self, instance: IdentityProviderConfig, validated_data: dict[str, Any]) -> IdentityProviderConfig:
        if "oidc_client_secret" in validated_data:
            validated_data["oidc_credentials"] = {"client_secret": validated_data.pop("oidc_client_secret")}
        scim_enabled = validated_data.pop("scim_enabled", None)
        organization_domains = validated_data.pop("organization_domains", None)
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
        if organization_domains is not None:
            self._sync_organization_domains(instance, organization_domains)
        self._scim_plain_token = scim_plain_token

        return instance

    @extend_schema_field(serializers.CharField)
    def get_scim_base_url(self, obj: IdentityProviderConfig) -> str:
        return get_scim_base_url(obj)

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

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        config = cast(IdentityProviderConfig, self.get_object())
        if config.config_scope is None:
            raise exceptions.ValidationError(
                "This identity provider configuration cannot be deleted until it has a feature scope.",
                code="unscoped_config",
            )

        return super().destroy(request, *args, **kwargs)

    @extend_schema(parameters=[SCIMRequestLogQuerySerializer], responses=PaginatedSCIMRequestLogSerializer)
    @action(methods=["GET"], detail=True, url_path="scim/logs")
    def scim_logs(self, request: Request, **kwargs: Any) -> response.Response:
        config = cast(IdentityProviderConfig, self.get_object())
        membership = OrganizationMembership.objects.filter(
            user=cast(User, request.user), organization=config.organization
        ).first()
        if not membership or membership.level < OrganizationMembership.Level.ADMIN:
            raise exceptions.PermissionDenied("Only organization admins can view SCIM logs.")

        queryset = SCIMRequestLog.objects.filter(identity_provider_config=config)
        return paginated_scim_request_logs_response(request, queryset)

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
