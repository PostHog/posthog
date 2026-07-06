import re
from typing import Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q, QuerySet

import django_filters
import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, request, response, serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.viewsets import ModelViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import OrgScopedPrimaryKeyRelatedField
from posthog.api.utils import action
from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature
from posthog.event_usage import groups
from posthog.models import OrganizationDomain, User
from posthog.models.identity_provider_config import IDP_CONFIG_SYNCED_FIELDS, IdentityProviderConfig
from posthog.models.organization import Organization, OrganizationMembership
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission

from ee.api.scim.utils import (
    disable_scim_for_domain,
    enable_scim_for_domain,
    get_scim_base_url,
    mask_email,
    mask_string,
    regenerate_scim_token,
)
from ee.models.scim_request_log import SCIMRequestLog

DOMAIN_REGEX = r"^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$"


class _OrgScopedIdentityProviderConfigField(OrgScopedPrimaryKeyRelatedField):
    # IdentityProviderConfig has a direct `organization` FK (not via team), so scope on it
    # directly. Scoping prevents linking a domain to (or probing) another org's config.
    scope_field = "organization"


def _capture_domain_event(request, domain: OrganizationDomain, event_type: str, properties: dict | None = None) -> None:
    if not properties:
        properties = {}

    properties.update(
        {
            "domain": domain.domain,
        }
    )

    posthoganalytics.capture(
        event=f"organization domain {event_type}",
        distinct_id=str(request.user.distinct_id),
        properties=properties,
        groups=groups(domain.organization),
    )


class OrganizationDomainSerializer(serializers.ModelSerializer):
    # Maps each verification-gated attribute's serializer source (the key seen in `validated_data`)
    # to the public field name used in error responses. The IdP fields are stored on the model as
    # underscore-prefixed attributes, so their source differs from the public name.
    UPDATE_ONLY_WHEN_VERIFIED = {
        "jit_provisioning_enabled": "jit_provisioning_enabled",
        "sso_enforcement": "sso_enforcement",
        "_scim_enabled": "scim_enabled",
        "_id_jag_issuer_url": "id_jag_issuer_url",
        "_id_jag_jwks_url": "id_jag_jwks_url",
        "_id_jag_allowed_clients": "id_jag_allowed_clients",
    }

    scim_base_url = serializers.SerializerMethodField()
    scim_bearer_token = serializers.SerializerMethodField()
    identity_provider_config = _OrgScopedIdentityProviderConfigField(
        queryset=IdentityProviderConfig.objects.all(),
        required=False,
        allow_null=True,
        help_text="Linked IdP configuration (SAML/SCIM/XAA) that backs this domain. Must belong to the same organization.",
    )
    # The IdP columns live on the model as underscore-prefixed attributes (read through the linked
    # config); these declarations keep the public API field names while sourcing the stored columns.
    saml_entity_id = serializers.CharField(
        source="_saml_entity_id",
        max_length=512,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="SAML IdP entity ID (issuer).",
    )
    saml_acs_url = serializers.CharField(
        source="_saml_acs_url",
        max_length=512,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="SAML single sign-on (ACS) URL.",
    )
    saml_x509_cert = serializers.CharField(
        source="_saml_x509_cert",
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="SAML IdP X.509 signing certificate (PEM).",
    )
    scim_enabled = serializers.BooleanField(
        source="_scim_enabled", required=False, help_text="Whether SCIM provisioning is enabled for this domain."
    )
    id_jag_issuer_url = serializers.CharField(
        source="_id_jag_issuer_url",
        max_length=512,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG on this domain.",
    )
    id_jag_jwks_url = serializers.CharField(
        source="_id_jag_jwks_url",
        max_length=512,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Override JWKS URL. Defaults to OIDC discovery on the issuer URL.",
    )
    id_jag_allowed_clients = serializers.ListField(
        source="_id_jag_allowed_clients",
        child=serializers.CharField(max_length=256),
        required=False,
        allow_empty=True,
        help_text="Allowed ID-JAG client IDs. Empty list allows any client_id.",
    )

    class Meta:
        model = OrganizationDomain
        fields = (
            "id",
            "domain",
            "is_verified",
            "verified_at",
            "verification_challenge",
            "jit_provisioning_enabled",
            "sso_enforcement",
            "has_saml",
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
            "identity_provider_config",
        )
        extra_kwargs = {
            "verified_at": {"read_only": True},
            "verification_challenge": {"read_only": True},
            "is_verified": {"read_only": True},
            "has_saml": {"read_only": True},
            "has_scim": {"read_only": True},
            "scim_base_url": {"read_only": True},
            "scim_bearer_token": {"read_only": True},
            "has_id_jag": {"read_only": True},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scim_plain_token: str | None = None

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None:
            fields["domain"].read_only = True
        return fields

    def create(self, validated_data: dict[str, Any]) -> OrganizationDomain:
        organization: Organization = self.context["view"].organization
        if is_cloud() and not organization.is_feature_available(AvailableFeature.AUTOMATIC_PROVISIONING):
            raise exceptions.PermissionDenied("Automatic provisioning is not enabled for this organization.")
        validated_data["organization"] = self.context["view"].organization
        validated_data.pop(
            "jit_provisioning_enabled", None
        )  # can never be set on creation because domain must be verified
        validated_data.pop("sso_enforcement", None)  # can never be set on creation because domain must be verified
        validated_data.pop("_scim_enabled", None)
        validated_data.pop("_id_jag_issuer_url", None)
        validated_data.pop("_id_jag_jwks_url", None)
        validated_data.pop("_id_jag_allowed_clients", None)
        instance: OrganizationDomain = super().create(validated_data)

        return instance

    def validate_domain(self, domain: str) -> str:
        if not re.match(DOMAIN_REGEX, domain):
            raise serializers.ValidationError("Please enter a valid domain or subdomain name.")
        return domain

    @staticmethod
    def _normalize_optional_url(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        return stripped.rstrip("/")

    def validate_id_jag_issuer_url(self, value: str | None) -> str | None:
        return self._normalize_optional_url(value)

    def validate_id_jag_jwks_url(self, value: str | None) -> str | None:
        return self._normalize_optional_url(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = cast(OrganizationDomain, self.instance)
        organization: Organization = self.context["view"].organization

        if instance and not instance.verified_at:
            for source_attr, public_name in self.UPDATE_ONLY_WHEN_VERIFIED.items():
                if source_attr in attrs:
                    raise serializers.ValidationError(
                        {public_name: "This attribute cannot be updated until the domain is verified."},
                        code="verification_required",
                    )
        if instance and attrs.get("jit_provisioning_enabled", None):
            if not organization.is_feature_available(AvailableFeature.AUTOMATIC_PROVISIONING):
                raise serializers.ValidationError(
                    {"jit_provisioning_enabled": "Automatic provisioning is not enabled for this organization."},
                    code="feature_not_available",
                )

        if instance and attrs.get("_scim_enabled") is not None:
            if not organization.is_feature_available(AvailableFeature.SCIM):
                raise serializers.ValidationError(
                    {"scim_enabled": "SCIM provisioning is not available for this organization."},
                    code="feature_not_available",
                )

        if instance and attrs.get("_id_jag_issuer_url"):
            if not organization.is_feature_available(AvailableFeature.XAA_AUTHENTICATION):
                raise serializers.ValidationError(
                    {"id_jag_issuer_url": "XAA (ID-JAG) is not available for this organization."},
                    code="feature_not_available",
                )

        return attrs

    def update(self, instance: OrganizationDomain, validated_data: dict[str, Any]) -> OrganizationDomain:
        validated_data.pop("domain", None)  # domain is immutable after creation
        scim_enabled = validated_data.pop("_scim_enabled", None)

        # When linking an IdP config (the source of truth), adopt its settings onto the domain's
        # legacy IdP columns so the forward mirror in `OrganizationDomain.save()` sees no
        # divergence to clobber. Explicit IdP fields in the same request still win (applied after,
        # by `super().update`).
        linked_config = validated_data.get("identity_provider_config")
        if linked_config is not None:
            for field in IDP_CONFIG_SYNCED_FIELDS:
                setattr(instance, f"_{field}", getattr(linked_config, field))

        instance = super().update(instance, validated_data)

        # Enable/disable SCIM only after `super().update()` has applied any newly linked
        # `identity_provider_config`, so the freshly generated token is mirrored to the
        # currently-linked config — never to a config the domain was previously linked to.
        scim_plain_token: str | None = None
        if scim_enabled is not None:
            if scim_enabled:
                if not instance._scim_enabled:
                    scim_plain_token = enable_scim_for_domain(instance)
            else:
                if instance._scim_enabled:
                    disable_scim_for_domain(instance)

        self._scim_plain_token = scim_plain_token

        id_jag_fields = {"_id_jag_issuer_url", "_id_jag_jwks_url", "_id_jag_allowed_clients"}
        if id_jag_fields.intersection(validated_data):
            try:
                instance.full_clean()
            except DjangoValidationError as e:
                # `clean()` keys errors by the model field name (underscore-prefixed); surface them
                # under the public API field name instead.
                errors = {(k[1:] if k.startswith("_id_jag_") else k): v for k, v in e.message_dict.items()}
                raise serializers.ValidationError(errors) from e

        return instance

    def get_scim_base_url(self, obj: OrganizationDomain) -> str | None:
        if not obj.has_scim:
            return None
        return get_scim_base_url(obj, self.context.get("request"))

    def get_scim_bearer_token(self, obj: OrganizationDomain) -> str | None:
        return getattr(self, "_scim_plain_token", None)


class SCIMRequestLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SCIMRequestLog
        fields = (
            "id",
            "request_method",
            "request_path",
            "request_headers",
            "request_body",
            "response_status",
            "response_body",
            "identity_provider",
            "duration_ms",
            "created_at",
        )
        read_only_fields = fields


class SCIMRequestLogPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _looks_like_email(value: str) -> bool:
    return "@" in value and "." in value.rpartition("@")[2]


def _search_scim_logs(queryset: QuerySet, _name: str, value: str) -> QuerySet:
    q = Q(request_path__icontains=value) | Q(request_body__icontains=value)
    if _looks_like_email(value):
        masked = mask_email(value)
        q = q | Q(request_body__icontains=masked)
    else:
        masked = mask_string(value)
        if masked != value:
            q = q | Q(request_body__icontains=masked)
    return queryset.filter(q)


class SCIMRequestLogFilter(django_filters.FilterSet):
    status_min = django_filters.NumberFilter(field_name="response_status", lookup_expr="gte")
    status_max = django_filters.NumberFilter(field_name="response_status", lookup_expr="lte")
    search = django_filters.CharFilter(method="filter_search")
    after = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    before = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = SCIMRequestLog
        fields: list[str] = []

    def filter_search(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        return _search_scim_logs(queryset, name, value)


@extend_schema(extensions={"x-product": "core"})
class OrganizationDomainViewset(TeamAndOrgViewSetMixin, ModelViewSet):
    scope_object = "organization"
    serializer_class = OrganizationDomainSerializer
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission]
    queryset = OrganizationDomain.objects.order_by("domain").all()

    @action(methods=["POST"], detail=True)
    def verify(self, request: request.Request, **kw) -> response.Response:
        instance = self.get_object()

        if instance.verified_at:
            raise exceptions.ValidationError("This domain has already been verified.", code="already_verified")

        instance, _ = instance.attempt_verification()

        serializer = self.get_serializer(instance=instance)
        return response.Response(serializer.data)

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()

        _capture_domain_event(
            request,
            instance,
            "created",
            properties={
                "jit_provisioning_enabled": instance.jit_provisioning_enabled,
                "sso_enforcement": instance.sso_enforcement or None,
            },
        )

        return response.Response(serializer.data, status=201)

    def _capture_domain_setting_event(self, request: Request) -> None:
        data = request.data
        if any(f.startswith("saml_") for f in data):
            event_type = "saml configured"
        elif any(f.startswith("id_jag_") for f in data):
            event_type = "id-jag configured"
        elif "sso_enforcement" in data:
            event_type = "sso enforcement updated"
        elif data.get("jit_provisioning_enabled") is True:
            event_type = "jit provisioning enabled"
        else:
            return

        _capture_domain_event(request, self.get_object(), event_type)

    def update(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        self._capture_domain_setting_event(request)
        return super().update(request, *args, **kwargs)

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        instance = self.get_object()

        _capture_domain_event(
            request,
            instance,
            "deleted",
            properties={
                "is_verified": instance.is_verified,
                "had_saml": instance.has_saml,
                "had_jit_provisioning": instance.jit_provisioning_enabled,
                "had_sso_enforcement": bool(instance.sso_enforcement),
                "had_scim": instance.has_scim,
                "had_id_jag": instance.has_id_jag,
            },
        )

        instance.delete()
        return response.Response(status=204)

    @action(methods=["POST"], detail=True, url_path="scim/token")
    def scim_token(self, request: Request, **kwargs) -> response.Response:
        """
        Regenerate SCIM bearer token.
        """
        domain: OrganizationDomain = self.get_object()

        if not domain.organization.is_feature_available(AvailableFeature.SCIM):
            raise exceptions.PermissionDenied("SCIM is not available for this organization")

        if not domain.has_scim:
            return response.Response(
                {"detail": "SCIM is not enabled for this domain"}, status=status.HTTP_400_BAD_REQUEST
            )

        plain_token = regenerate_scim_token(domain)

        return response.Response(
            {
                "scim_enabled": True,
                "scim_base_url": get_scim_base_url(domain, request),
                "scim_bearer_token": plain_token,
            }
        )

    @action(methods=["GET"], detail=True, url_path="scim/logs")
    def scim_logs(self, request: Request, **kwargs) -> response.Response:
        membership = OrganizationMembership.objects.filter(
            user=cast("User", request.user), organization=self.organization
        ).first()
        if not membership or membership.level < OrganizationMembership.Level.ADMIN:
            raise exceptions.PermissionDenied("Only organization admins can view SCIM logs.")

        domain: OrganizationDomain = self.get_object()
        queryset = SCIMRequestLog.objects.filter(organization_domain=domain)
        queryset = SCIMRequestLogFilter(request.query_params, queryset=queryset).qs

        paginator = SCIMRequestLogPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = SCIMRequestLogSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
