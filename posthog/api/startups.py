from typing import Any

from django.utils import timezone
from rest_framework import response, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.viewsets import ViewSet

from posthog.models import Organization

from posthog.models.organization import OrganizationMembership


class StartupApplicationSerializer(serializers.Serializer):
    program = serializers.ChoiceField(
        required=True,
        choices=["startups", "yc"],
        help_text="Program type - 'startups' for regular startup program, 'yc' for Y Combinator startups",
    )
    organization_id = serializers.CharField(required=True)
    # add customer_id

    # Startup program fields
    raised = serializers.CharField(required=False)
    incorporation_date = serializers.DateField(required=False)

    # YC program fields
    yc_batch = serializers.CharField(required=False)
    yc_proof_screenshot_url = serializers.URLField(required=False)
    yc_merch_count = serializers.IntegerField(required=False, min_value=0, max_value=5)

    def validate_organization_id(self, value: str) -> str:
        try:
            organization = Organization.objects.get(id=value)

            user = self.context["request"].user
            membership = organization.memberships.filter(user=user).first()
            if not membership or not membership.level >= OrganizationMembership.Level.ADMIN:
                raise ValidationError("You must be an organization admin or owner to apply")

            # TODO: Check if already in startup program and if has active subscription

        except Organization.DoesNotExist:
            raise ValidationError("Organization not found")
        return value

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        program = data["program"]
        errors: dict[str, str] = {}

        if program == "startups":
            if not data.get("raised"):
                errors["raised"] = "Funding amount is required for startup program applications"
            elif not isinstance(data["raised"], str):
                errors["raised"] = "Funding amount must be a string"
            else:
                try:
                    amount = int(data["raised"])
                    if amount >= 5_000_000:
                        errors["raised"] = (
                            "Companies that have raised $5M or more are not eligible for the startup program"
                        )
                except ValueError:
                    errors["raised"] = "Invalid funding amount"

            if not data.get("incorporation_date"):
                errors["incorporation_date"] = "Incorporation date is required for startup program applications"
            elif (timezone.now().date() - data["incorporation_date"]).days > 730:  # 2 years
                errors["incorporation_date"] = "Companies older than 2 years are not eligible for the startup program"

            # Remove YC fields for startups program
            data.pop("yc_batch", None)
            data.pop("yc_proof_screenshot_url", None)
            data.pop("yc_merch_count", None)

        elif program == "yc":
            if not data.get("yc_batch"):
                errors["yc_batch"] = "YC batch is required for YC applications"
            if not data.get("yc_proof_screenshot_url"):
                errors["yc_proof_screenshot_url"] = "Screenshot proof is required for YC applications"

            # Remove startup fields for YC program
            data.pop("raised", None)
            data.pop("incorporation_date", None)

        else:
            errors["program"] = f"Invalid program type: {program}"

        if errors:
            raise ValidationError(errors)

        return data

    def create(self, validated_data: dict[str, Any]) -> dict[str, Any]:
        user = self.context["request"].user
        organization = Organization.objects.get(id=validated_data["organization_id"])

        submission_data = {
            # User data
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            # Organization data
            "organization_name": organization.name,
            "organization_id": organization.id,
            "customer_id": organization.customer_id,
            # Application data
            **validated_data,
        }

        # TODO: Send to external services
        # 1. Format for Zapier
        # 2. Send to Zapier webhook
        # 3. Format for Salesforce
        # 4. Send to Salesforce

        return submission_data


class StartupsViewSet(ViewSet):
    """Handles startup-related functionality."""

    @action(detail=False, methods=["POST"])
    def apply(self, request, *args, **kwargs):
        """Submit startup program application."""
        if not request.user.is_authenticated:
            raise ValidationError("You must be logged in to apply for the startup program")

        serializer = StartupApplicationSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        try:
            result = serializer.save()
            return response.Response(result, status=status.HTTP_201_CREATED)
        except Exception:
            raise ValidationError("Failed to submit application")
