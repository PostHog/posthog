"""
Implements the Vercel Marketplace API server for managing marketplace resources.

See:
https://vercel.com/docs/integrations/create-integration/marketplace-api
"""

from typing import Any
from rest_framework import serializers, viewsets, exceptions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import mixins
from posthog.auth import VercelAuthentication
from posthog.api.vercel_installation import VercelInstallationPermission, get_vercel_plans
from posthog.models.organization import Organization
from posthog.models.vercel_resouce import VercelResource
from posthog.models.vercel_installation import VercelInstallation
from posthog.models.team.team import Team


class VercelResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = VercelResource
        fields = "__all__"


class VercelBillingPlanDetailSerializer(serializers.Serializer):
    label = serializers.CharField(min_length=1)
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
        help_text="Optional, ignored unless plan type is `prepayment`. The minimum amount of credits a user can purchase at a time. The value is a decimal string representation of the USD amount, e.g. '4.39' for $4.39 USD as the minumum amount.",
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


# class VercelResourceResponseSerializer(serializers.Serializer):
#     """Response serializer for provisioned resources according to Vercel OpenAPI spec"""

#     id = serializers.CharField(help_text="The partner-specific ID of the resource")
#     productId = serializers.CharField(help_text="The partner-specific ID/slug of the product")
#     protocolSettings = VercelProtocolSettingsSerializer(required=False)
#     billingPlan = VercelBillingPlanSerializer(required=False)
#     name = serializers.CharField(help_text="User-inputted name for the resource")
#     metadata = serializers.DictField(child=serializers.JSONField())
#     status = serializers.ChoiceField(choices=["ready", "pending", "suspended", "resumed", "uninstalled", "error"])
#     notification = VercelNotificationSerializer(required=False)
#     secrets = serializers.ListField(child=VercelSecretSerializer(), min_length=1)


class VercelResourceViewSet(
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = VercelResourceSerializer
    lookup_field = "id"
    queryset = VercelResource.objects.all()
    authentication_classes = [VercelAuthentication]
    permission_classes = [VercelInstallationPermission]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Used to provision a resource via POST.
        https://vercel.com/docs/integrations/create-integration/marketplace-api#provision-resource
        """
        serializer = ResourcePayloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        installation_id = self.kwargs.get("parent_lookup_installation_id")

        try:
            installation = VercelInstallation.objects.get(id=installation_id)
        except VercelInstallation.DoesNotExist:
            raise exceptions.NotFound("Installation not found")

        organization: Organization = installation.organization

        team = Team.objects.create_with_data(
            initiating_user=None,
            organization=organization,
            name=validated_data["name"],
        )
        resource: VercelResource = VercelResource.objects.create(
            team=team,
            installation=installation,
            resource_id=str(team.pk),  # TODO: Drop this field.
            config=validated_data,  # TODO: Drop this field.
        )

        secrets = [
            {
                "name": "POSTHOG_PROJECT_API_KEY",
                "value": team.api_token,
            },
            {
                "name": "POSTHOG_HOST",
                "value": "https://app.posthog.com",
            },
        ]

        response_data = {
            "id": str(resource.pk),
            "productId": validated_data["productId"],
            "name": validated_data["name"],
            "metadata": validated_data["metadata"],
            "status": "ready",
            "secrets": secrets,
        }

        return Response(response_data, status=200)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        https://vercel.com/docs/integrations/create-integration/marketplace-api#get-resource
        """
        resource = self.get_object()
        team = resource.team

        # Get installation_id from kwargs
        installation_id = self.kwargs.get("parent_lookup_installation_id")

        installation = VercelInstallation.objects.get(installation_id=installation_id)

        billing_plans = get_vercel_plans()
        current_plan_id = installation.billing_plan_id

        current_plan = next((plan for plan in billing_plans if plan["id"] == current_plan_id), None)

        response_data = {
            "id": str(resource.pk),
            "productId": resource.config.get("productId", ""),
            "name": resource.config.get("name", team.name),
            "metadata": resource.config.get("metadata", {}),
            "status": "ready",
            "secrets": [
                {
                    "name": "POSTHOG_PROJECT_API_KEY",
                    "value": team.api_token,
                },
                {
                    "name": "POSTHOG_HOST",
                    "value": "https://app.posthog.com",
                },
            ],
            "billingPlan": current_plan,
        }

        return Response(response_data, status=200)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        https://vercel.com/docs/integrations/create-integration/marketplace-api#update-resource
        """
        # TODO: Implement resource update logic
        raise serializers.MethodNotAllowed("PATCH")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        https://vercel.com/docs/integrations/create-integration/marketplace-api#delete-resource
        """
        # TODO: Implement resource deletion logic
        raise serializers.MethodNotAllowed("DELETE")
