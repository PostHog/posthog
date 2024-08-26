import re
from typing import Any, cast

from rest_framework import exceptions, request, response, serializers
from posthog.api.utils import action
from rest_framework.viewsets import ModelViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature
from posthog.models import OrganizationDomain
from posthog.models.organization import Organization
from posthog.permissions import OrganizationAdminWritePermissions

DOMAIN_REGEX = r"^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$"


class OrganizationDomainSerializer(serializers.ModelSerializer):
    UPDATE_ONLY_WHEN_VERIFIED = ["jit_provisioning_enabled", "sso_enforcement"]

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
        )
        extra_kwargs = {
            "verified_at": {"read_only": True},
            "verification_challenge": {"read_only": True},
            "is_verified": {"read_only": True},
            "has_saml": {"read_only": True},
        }

    def create(self, validated_data: dict[str, Any]) -> OrganizationDomain:
        organization: Organization = self.context["view"].organization
        if is_cloud() and not organization.is_feature_available(AvailableFeature.AUTOMATIC_PROVISIONING):
            raise exceptions.PermissionDenied("Automatic provisioning is not enabled for this organization.")
        validated_data["organization"] = self.context["view"].organization
        validated_data.pop(
            "jit_provisioning_enabled", None
        )  # can never be set on creation because domain must be verified
        validated_data.pop("sso_enforcement", None)  # can never be set on creation because domain must be verified
        instance: OrganizationDomain = super().create(validated_data)

        return instance

    def validate_domain(self, domain: str) -> str:
        if not re.match(DOMAIN_REGEX, domain):
            raise serializers.ValidationError("Please enter a valid domain or subdomain name.")
        return domain

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = cast(OrganizationDomain, self.instance)

        if instance and not instance.verified_at:
            for protected_attr in self.UPDATE_ONLY_WHEN_VERIFIED:
                if protected_attr in attrs:
                    raise serializers.ValidationError(
                        {protected_attr: "This attribute cannot be updated until the domain is verified."},
                        code="verification_required",
                    )
        if instance and attrs.get("jit_provisioning_enabled", None):
            organization: Organization = self.context["view"].organization
            if not organization.is_feature_available(AvailableFeature.AUTOMATIC_PROVISIONING):
                raise serializers.ValidationError(
                    {"jit_provisioning_enabled": "Automatic provisioning is not enabled for this organization."},
                    code="feature_not_available",
                )

        return attrs


class OrganizationDomainViewset(TeamAndOrgViewSetMixin, ModelViewSet):
    scope_object = "organization"
    serializer_class = OrganizationDomainSerializer
    permission_classes = [OrganizationAdminWritePermissions]
    queryset = OrganizationDomain.objects.order_by("domain").all()

    @action(methods=["POST"], detail=True)
    def verify(self, request: request.Request, **kw) -> response.Response:
        instance = self.get_object()

        if instance.verified_at:
            raise exceptions.ValidationError("This domain has already been verified.", code="already_verified")

        instance, _ = instance.attempt_verification()

        serializer = self.get_serializer(instance=instance)
        return response.Response(serializer.data)
