from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.api.scim.utils import disable_scim_for_domain, enable_scim_for_domain, get_scim_base_url, regenerate_scim_token
from posthog.api.organization_domain import OrganizationDomainViewset
from posthog.models.organization_domain import OrganizationDomain


class SCIMConfigSerializer(serializers.Serializer):
    scim_enabled = serializers.BooleanField(read_only=True)
    scim_base_url = serializers.CharField(read_only=True)
    scim_bearer_token = serializers.CharField(read_only=True, required=False)


class OrganizationDomainSCIMMixin:
    """
    Mixin to add SCIM management endpoints to OrganizationDomainViewset.
    """

    @action(methods=["GET", "POST"], detail=True, url_path="scim")
    def scim_config(self, request: Request, **kwargs) -> Response:
        """
        GET: Retrieve SCIM configuration (without token)
        POST: Enable SCIM and generate a new bearer token
        """
        domain: OrganizationDomain = self.get_object()

        if request.method == "GET":
            return Response(
                {
                    "scim_enabled": domain.scim_enabled,
                    "scim_base_url": get_scim_base_url(domain, request) if domain.has_scim else None,
                }
            )

        elif request.method == "POST":
            # Enable SCIM and generate token
            plain_token = enable_scim_for_domain(domain)

            return Response(
                {
                    "scim_enabled": True,
                    "scim_base_url": get_scim_base_url(domain, request),
                    "scim_bearer_token": plain_token,  # Only returned once!
                },
                status=status.HTTP_201_CREATED,
            )

    @action(methods=["POST"], detail=True, url_path="scim/regenerate")
    def scim_regenerate_token(self, request: Request, **kwargs) -> Response:
        """
        Regenerate SCIM bearer token.
        """
        domain: OrganizationDomain = self.get_object()

        if not domain.scim_enabled:
            return Response({"detail": "SCIM is not enabled for this domain"}, status=status.HTTP_400_BAD_REQUEST)

        plain_token = regenerate_scim_token(domain)

        return Response(
            {
                "scim_enabled": True,
                "scim_base_url": get_scim_base_url(domain, request),
                "scim_bearer_token": plain_token,  # Only returned once!
            }
        )

    @action(methods=["POST"], detail=True, url_path="scim/disable")
    def scim_disable(self, request: Request, **kwargs) -> Response:
        """
        Disable SCIM for this domain.
        """
        domain: OrganizationDomain = self.get_object()

        disable_scim_for_domain(domain)

        return Response({"scim_enabled": False}, status=status.HTTP_200_OK)


# Note: To use this mixin, update OrganizationDomainViewset to inherit from it:
# class OrganizationDomainViewset(OrganizationDomainSCIMMixin, ...):
