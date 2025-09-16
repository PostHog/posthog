"""
Implements the Vercel Marketplace API server for managing marketplace resources.
See:
https://vercel.com/docs/integrations/create-integration/marketplace-api
"""

from typing import Any

from rest_framework import exceptions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from ee.api.authentication import VercelAuthentication
from ee.api.vercel.vercel_installation import VercelErrorResponseMixin, validate_installation_id
from ee.api.vercel.vercel_permission import VercelPermission
from ee.api.vercel.vercel_region_proxy_mixin import VercelRegionProxyMixin
from ee.vercel.integration import VercelIntegration


class VercelBillingPlanDetailSerializer(serializers.Serializer):
    label = serializers.CharField(min_length=1)  # type: ignore
    value = serializers.CharField(min_length=1)


class VercelBillingPlanQuoteLineSerializer(serializers.Serializer):
    line = serializers.CharField(min_length=1)
    amount = serializers.CharField(min_length=1)


class VercelBillingPlanSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Partner-provided billing plan. Example: 'pro200'")
    type = serializers.ChoiceField(choices=["prepayment", "subscription"], help_text="Type of billing plan")
    name = serializers.CharField(help_text="Name of the plan. Example: 'Hobby'")
    scope = serializers.ChoiceField(
        choices=["installation", "resource"],
        default="resource",
        help_text="Plan scope. To use `installation` level billing plans, Installation-level Billing Plans must be enabled on your integration",
    )
    description = serializers.CharField(help_text="Example: 'Use all you want up to 20G'")
    paymentMethodRequired = serializers.BooleanField(
        default=True,
        help_text="Only used if plan type is `subscription`. Set this field to `false` if this plan is completely free.",
    )
    preauthorizationAmount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        help_text="Only used if plan type is `subscription` and `paymentMethodRequired` is `true`. The amount will be used to test if the user's payment method can handle the charge. Example: 10.53 for $10.53 USD.",
    )
    initialCharge = serializers.CharField(
        required=False,
        help_text="Only used if plan type is `subscription` and `paymentMethodRequired` is `true`. The amount that the partner will invoice immediately at sign-up. Example: 20.00 for $20.00 USD.",
    )
    minimumAmount = serializers.CharField(
        required=False,
        help_text="Optional, ignored unless plan type is `prepayment`. The minimum amount of credits a user can purchase at a time. The value is a decimal string representation of the USD amount, e.g. '4.39' for $4.39 USD as the minimum amount.",
    )
    maximumAmount = serializers.CharField(
        required=False,
        help_text="Optional, ignored unless plan type is `prepayment`. The maximum amount of credits a user can purchase at a time. The value is a decimal string representation of the USD amount, e.g. '86.82' for $86.82 USD as the maximum amount.",
    )
    maximumAmountAutoPurchasePerPeriod = serializers.CharField(
        required=False,
        help_text="Optional, ignored unless plan type is `prepayment`. The maximum amount of credits the system can auto-purchase in any period (month). The value is a decimal string representation of the USD amount, e.g. '86.82' for $86.82 USD as the maximum amount.",
    )
    cost = serializers.CharField(
        required=False,
        help_text="Plan's cost, if available. Only relevant for fixed-cost plans. Example: '$20.00/month'",
    )
    details = serializers.ListField(
        child=VercelBillingPlanDetailSerializer(), required=False, help_text="Plan's details"
    )
    highlightedDetails = serializers.ListField(
        child=VercelBillingPlanDetailSerializer(), required=False, help_text="Highlighted plan's details"
    )
    quote = serializers.ListField(
        child=VercelBillingPlanQuoteLineSerializer(), required=False, help_text="Deprecated. Use `details` instead."
    )
    effectiveDate = serializers.DateTimeField(
        required=False, help_text="Date/time when the plan becomes effective. Important for billing plan changes."
    )
    disabled = serializers.BooleanField(
        required=False,
        help_text="If true, the plan is disabled and cannot be selected. Example: 'disabled': true` for 'Hobby' plan.",
    )


class VercelNotificationSerializer(serializers.Serializer):
    level = serializers.ChoiceField(choices=["info", "warn", "error"], help_text="Notification level")
    title = serializers.CharField(min_length=1, help_text="Notification title")
    message = serializers.CharField(min_length=1, max_length=500, required=False, help_text="Notification message")
    href = serializers.URLField(required=False, help_text="Absolute or SSO URL. SSO URLs start with 'sso:'.")


class VercelSecretEnvironmentOverridesSerializer(serializers.Serializer):
    development = serializers.CharField(required=False, help_text="Value for development environment")
    preview = serializers.CharField(required=False, help_text="Value for preview environment")
    production = serializers.CharField(required=False, help_text="Value for production environment")


class VercelSecretSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=1, help_text="Name of the secret")
    value = serializers.CharField(min_length=1, help_text="Value of the secret")
    prefix = serializers.CharField(required=False, help_text="Deprecated")
    environmentOverrides = VercelSecretEnvironmentOverridesSerializer(required=False)


class VercelExperimentationSettingsSerializer(serializers.Serializer):
    edgeConfigId = serializers.CharField(
        help_text="An Edge Config selected by the user for partners to push data into."
    )


class VercelProtocolSettingsSerializer(serializers.Serializer):
    experimentation = VercelExperimentationSettingsSerializer(required=False)


class ResourcePayloadSerializer(serializers.Serializer):
    productId = serializers.CharField(help_text="The partner-specific ID/slug of the product. Example: 'redis'")
    name = serializers.CharField(help_text="User-inputted name for the resource.")
    metadata = serializers.DictField(
        child=serializers.JSONField(), help_text="User-inputted metadata based on the registered metadata schema."
    )
    billingPlanId = serializers.CharField(help_text="Partner-provided billing plan. Example: 'pro200'")
    externalId = serializers.CharField(
        required=False,
        help_text="A partner-provided identifier used to indicate the source of the resource provisioning. In the Deploy Button flow, the externalId will equal the external-id query parameter.",
    )
    protocolSettings = serializers.DictField(
        required=False,
        child=serializers.DictField(
            child=serializers.CharField(
                required=False, help_text="An Edge Config selected by the user for partners to push data into."
            ),
            required=False,
        ),
    )


class ResourceResponseSerializer(serializers.Serializer):
    id = serializers.CharField()
    productId = serializers.CharField()
    name = serializers.CharField()
    metadata = serializers.DictField()
    status = serializers.CharField()
    billingPlan = VercelBillingPlanSerializer(required=False, allow_null=True)
    notification = VercelNotificationSerializer(required=False)
    secrets = serializers.ListField(child=VercelSecretSerializer(), required=False)
    protocolSettings = VercelProtocolSettingsSerializer(required=False)


def validate_resource_id(resource_id: str | None) -> str:
    if not resource_id or not resource_id.isdigit() or int(resource_id) <= 0:
        raise exceptions.ValidationError({"resource_id": "Invalid Resource ID"})
    return resource_id


class VercelResourceViewSet(VercelRegionProxyMixin, VercelErrorResponseMixin, viewsets.GenericViewSet):
    lookup_field = "resource_id"
    authentication_classes = [VercelAuthentication]
    permission_classes = [VercelPermission]

    vercel_supported_auth_types = {
        "create": ["user"],
        "update": ["user"],
        "partial_update": ["user"],
        "destroy": ["user", "system"],
        "retrieve": ["system"],
    }

    def _validate_resource_access(self, resource_id: str, installation_id: str) -> None:
        resource, installation = VercelIntegration._get_resource_with_installation(resource_id)
        if installation.integration_id != installation_id:
            raise exceptions.ValidationError({"resource": "Resource does not belong to this installation."})

    def _validate_response_format(self, data: dict[str, Any]) -> dict[str, Any]:
        serializer = ResourceResponseSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        https://vercel.com/docs/integrations/create-integration/marketplace-api#provision-resource
        """
        serializer = ResourcePayloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        installation_id = validate_installation_id(self.kwargs.get("parent_lookup_installation_id"))
        response_data = VercelIntegration.create_resource(installation_id, serializer.validated_data)
        validated_response = self._validate_response_format(response_data)
        return Response(validated_response, status=200)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        https://vercel.com/docs/integrations/create-integration/marketplace-api#get-resource
        """
        resource_id = validate_resource_id(self.kwargs.get("resource_id"))
        installation_id = validate_installation_id(self.kwargs.get("parent_lookup_installation_id"))
        self._validate_resource_access(resource_id, installation_id)

        response_data = VercelIntegration.get_resource(resource_id)
        validated_response = self._validate_response_format(response_data)
        return Response(validated_response, status=200)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        https://vercel.com/docs/integrations/create-integration/marketplace-api#update-resource
        """
        serializer = ResourcePayloadSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        resource_id = validate_resource_id(self.kwargs.get("resource_id"))
        installation_id = validate_installation_id(self.kwargs.get("parent_lookup_installation_id"))
        self._validate_resource_access(resource_id, installation_id)

        response_data = VercelIntegration.update_resource(resource_id, serializer.validated_data)
        validated_response = self._validate_response_format(response_data)
        return Response(validated_response, status=200)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        https://vercel.com/docs/integrations/create-integration/marketplace-api#delete-resource
        """
        resource_id = validate_resource_id(self.kwargs.get("resource_id"))
        installation_id = validate_installation_id(self.kwargs.get("parent_lookup_installation_id"))
        self._validate_resource_access(resource_id, installation_id)

        VercelIntegration.delete_resource(resource_id)
        return Response(status=204)
