from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction

import structlog
from rest_framework import exceptions

from posthog.event_usage import report_user_signed_up
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.product_intent import ProductIntent
from posthog.models.team import Team
from posthog.models.user import User

logger = structlog.get_logger(__name__)


class VercelIntegration:
    @staticmethod
    def _get_installation(installation_id: str) -> OrganizationIntegration:
        try:
            return OrganizationIntegration.objects.get(
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL, integration_id=installation_id
            )
        except OrganizationIntegration.DoesNotExist:
            raise exceptions.NotFound("Installation not found")

    @staticmethod
    def _get_resource(resource_id: str) -> Integration:
        try:
            return Integration.objects.get(pk=resource_id, kind=Integration.IntegrationKind.VERCEL)
        except Integration.DoesNotExist:
            raise exceptions.NotFound("Resource not found")

    @staticmethod
    def get_vercel_plans() -> list[dict[str, Any]]:
        # TODO: Retrieve through billing service instead.
        return [
            {
                "id": "free",
                "type": "subscription",
                "name": "Free",
                "description": "No credit card required",
                "scope": "installation",
                "paymentMethodRequired": False,
                "details": [
                    {"label": "Data retention", "value": "1 year"},
                    {"label": "Projects", "value": "1"},
                    {"label": "Team members", "value": "Unlimited"},
                    {"label": "API Access", "value": "✓"},
                    {"label": "No limits on tracked users", "value": "✓"},
                    {"label": "Community support", "value": "Support via community forum"},
                ],
                "highlightedDetails": [
                    {"label": "Feature Flags", "value": "1 million free requests"},
                    {"label": "Experiments", "value": "1 million free requests"},
                ],
            },
            {
                "id": "pay_as_you_go",
                "type": "subscription",
                "name": "Pay-as-you-go",
                "description": "Usage-based pricing after free tier",
                "scope": "installation",
                "paymentMethodRequired": True,
                "details": [
                    {"label": "Data retention", "value": "7 years"},
                    {"label": "Projects", "value": "6"},
                    {"label": "Team members", "value": "Unlimited"},
                    {"label": "API Access", "value": "✓"},
                    {"label": "No limits on tracked users", "value": "✓"},
                    {"label": "Standard support", "value": "Support via email, Slack-based over $2k/mo"},
                ],
                "highlightedDetails": [
                    {"label": "Feature flags", "value": "1 million requests for free, then from $0.0001/request"},
                    {"label": "Experiments", "value": "Billed with feature flags"},
                ],
            },
        ]

    @staticmethod
    def upsert_installation(installation_id: str, payload: dict[str, Any]) -> None:
        logger.info("Starting Vercel installation upsert process", installation_id=installation_id)

        # Check if there's already an OrganizationIntegration for this installation_id
        # If there is, we don't need to do update anything besides OrganizationIntegration's config.
        organization_integration_exists = OrganizationIntegration.objects.filter(
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=installation_id,
        ).exists()

        if organization_integration_exists:
            OrganizationIntegration.objects.filter(
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
                integration_id=installation_id,
            ).update(config=payload)
            logger.info("Vercel installation updated", installation_id=installation_id)
            return

        email = payload.get("account", {}).get("contact", {}).get("email")
        if not email:
            logger.exception("Vercel installation payload missing email", installation_id=installation_id)
            raise exceptions.ValidationError(
                {"validation_error": "Email is required in the payload."},
                code="invalid",
            )

        # It's possible that there's already a user with this email signed up to PostHog,
        # either due to a reinstallation of the integration, or manual signup through PostHog itself.
        user = User.objects.filter(email=email).first()
        user_created = False

        with transaction.atomic():
            try:
                if not user:
                    user = User.objects.create_user(
                        email=payload["account"]["contact"]["email"],
                        password=None,
                        first_name=payload["account"]["contact"].get("name", ""),
                        is_staff=False,
                        is_email_verified=False,
                    )
                    user_created = True

                # Through Vercel we can only create new organizations, not use existing ones.
                # Note: We won't create a team here, that's done during Vercel resource creation.
                organization = Organization.objects.create(
                    name=payload["account"].get("name", f"Vercel Installation {installation_id}")
                )

                user.join(organization=organization, level=OrganizationMembership.Level.OWNER)

                OrganizationIntegration.objects.update_or_create(
                    organization=organization,
                    kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
                    integration_id=installation_id,
                    defaults={
                        "config": payload,
                        "created_by": user,
                    },
                )

                logger.info("Created new Vercel installation", installation_id=installation_id)
            except IntegrityError as e:
                capture_exception(e)
                logger.exception("Failed to create Vercel installation", installation_id=installation_id)
                raise exceptions.ValidationError(
                    {"validation_error": "Something went wrong."},
                    code="unique",
                )

        if user_created:
            report_user_signed_up(
                user,
                is_instance_first_user=False,
                is_organization_first_user=True,
                backend_processor="VercelIntegration",
                user_analytics_metadata=user.get_analytics_metadata(),
                org_analytics_metadata=organization.get_analytics_metadata(),
                social_provider="vercel",
                referral_source="vercel",
            )

        logger.info(
            "Successfully created Vercel installation", installation_id=installation_id, organization_id=organization.id
        )

    @staticmethod
    def get_installation_billing_plan(installation_id: str) -> dict[str, Any]:
        VercelIntegration._get_installation(installation_id)
        billing_plans = VercelIntegration.get_vercel_plans()

        # Always return free plan for now - will be replaced with billing service
        current_plan = next(plan for plan in billing_plans if plan["id"] == "free")

        return {
            "billingplan": current_plan,
        }

    @staticmethod
    def update_installation(installation_id: str, billing_plan_id: str) -> None:
        logger.info("Starting Vercel installation update", installation_id=installation_id)

        # TODO: Implement billing plan update logic here, awaiting billing service implementation.

        logger.info("Successfully updated Vercel installation", installation_id=installation_id)

    @staticmethod
    def delete_installation(installation_id: str) -> dict[str, Any]:
        logger.info("Starting Vercel installation deletion", installation_id=installation_id)
        installation = VercelIntegration._get_installation(installation_id)
        installation.delete()
        is_dev = settings.DEBUG
        logger.info(
            "Successfully deleted Vercel installation",
            installation_id=installation_id,
            finalized=is_dev,
        )
        return {"finalized": is_dev}  # Immediately finalize in dev mode for testing purposes

    @staticmethod
    def get_product_plans(product_slug: str) -> dict[str, Any]:
        if product_slug != "posthog":
            raise exceptions.NotFound("Product not found")

        return {"plans": VercelIntegration.get_vercel_plans()}

    @staticmethod
    def create_resource(installation_id: str, resource_data: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "Starting Vercel resource creation",
            installation_id=installation_id,
            resource_name=resource_data.get("name"),
        )

        if not resource_data.get("name"):
            raise exceptions.ValidationError({"name": "Resource name is required."})

        installation = VercelIntegration._get_installation(installation_id)
        organization: Organization = installation.organization

        team = Team.objects.create_with_data(
            initiating_user=None,
            organization=organization,
            name=resource_data["name"],
            has_completed_onboarding_for={
                "product_analytics": True
            },  # Mark one product as onboarded to show quick start sidebar
        )

        ProductIntent.objects.create(
            team=team,
            product_type="feature_flags",
            contexts={"vercel integration": 1},
        )

        ProductIntent.objects.create(
            team=team,
            product_type="experiments",
            contexts={"vercel integration": 1},
        )

        resource = Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config=resource_data,
            created_by=installation.created_by,
        )

        logger.info(
            "Successfully created Vercel resource",
            installation_id=installation_id,
            resource_id=resource.pk,
            team_id=team.pk,
        )

        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def get_resource(resource_id: str, installation_id: str) -> dict[str, Any]:
        resource = VercelIntegration._get_resource(resource_id)
        installation = VercelIntegration._get_installation(installation_id)
        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def update_resource(resource_id: str, installation_id: str, resource_data: dict[str, Any]) -> dict[str, Any]:
        logger.info("Starting Vercel resource update", resource_id=resource_id, installation_id=installation_id)
        resource = VercelIntegration._get_resource(resource_id)
        installation = VercelIntegration._get_installation(installation_id)

        updated_config = resource.config.copy()
        updated_config.update(resource_data)
        resource.config = updated_config
        resource.save(update_fields=["config"])

        logger.info("Successfully updated Vercel resource", resource_id=resource_id)
        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def delete_resource(resource_id: str, installation_id: str | None = None) -> None:
        logger.info("Starting Vercel resource deletion", resource_id=resource_id, installation_id=installation_id)
        resource = VercelIntegration._get_resource(resource_id)

        if installation_id:
            installation = VercelIntegration._get_installation(installation_id)
            if resource.team.organization != installation.organization:
                raise exceptions.ValidationError({"resource": "Resource does not belong to this installation."})

        resource.delete()
        logger.info("Successfully deleted Vercel resource", resource_id=resource_id)

    @staticmethod
    def _build_resource_response(resource: Integration, installation: OrganizationIntegration) -> dict[str, Any]:
        billing_plans = VercelIntegration.get_vercel_plans()
        current_plan_id = installation.config.get("billing_plan_id", "free")
        current_plan = next((plan for plan in billing_plans if plan["id"] == current_plan_id), None)

        return {
            "id": str(resource.pk),
            "productId": resource.config.get("productId", ""),
            "name": resource.config.get("name", resource.team.name),
            "metadata": resource.config.get("metadata", {}),
            "status": "ready",
            "secrets": VercelIntegration._build_secrets(resource.team),
            "billingPlan": current_plan,
        }

    @staticmethod
    def _build_secrets(team: Team) -> list[dict[str, str]]:
        return [
            {
                "name": "POSTHOG_PROJECT_API_KEY",
                "value": team.api_token,
            },
            {
                "name": "POSTHOG_HOST",
                "value": "https://us.posthog.com",
            },
        ]
