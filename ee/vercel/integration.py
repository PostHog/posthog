import copy
from dataclasses import asdict, dataclass
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
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)


@dataclass
class ResourceConfig:
    productId: str
    name: str
    metadata: dict[str, Any]
    billingPlanId: str
    externalId: str | None = None
    protocolSettings: dict[str, Any] | None = None


@dataclass
class InstallationCredentials:
    access_token: str
    token_type: str


@dataclass
class InstallationContact:
    email: str
    name: str | None = None


@dataclass
class InstallationAccount:
    url: str
    contact: InstallationContact
    name: str | None = None


@dataclass
class InstallationConfig:
    scopes: list[str]
    acceptedPolicies: dict[str, Any]
    credentials: InstallationCredentials
    account: InstallationAccount


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
    def _validate_resource_belongs_to_installation(
        resource: Integration, installation: OrganizationIntegration
    ) -> None:
        if not resource.team.organization.organizationintegration_set.filter(
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL, integration_id=installation.integration_id
        ).exists():
            raise exceptions.ValidationError({"resource": "Resource does not belong to this installation."})

    @staticmethod
    def _get_resource_with_installation(resource_id: str) -> tuple[Integration, OrganizationIntegration]:
        resource = VercelIntegration._get_resource(resource_id)
        org_integration = resource.team.organization.organizationintegration_set.get(
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL
        )
        if not org_integration.integration_id:
            raise exceptions.NotFound("Installation not found")
        installation = VercelIntegration._get_installation(org_integration.integration_id)
        return resource, installation

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
        account_data = payload.get("account", {})
        contact_data = account_data.get("contact", {})
        credentials_data = payload.get("credentials", {})

        contact = InstallationContact(email=contact_data["email"], name=contact_data.get("name"))

        credentials = InstallationCredentials(
            access_token=credentials_data["access_token"], token_type=credentials_data["token_type"]
        )

        account = InstallationAccount(url=account_data["url"], contact=contact, name=account_data.get("name"))

        config = InstallationConfig(
            scopes=payload["scopes"],
            acceptedPolicies=payload["acceptedPolicies"],
            credentials=credentials,
            account=account,
        )

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
            ).update(config=asdict(config))
            logger.info("Vercel installation updated", installation_id=installation_id)
            return

        # It's possible that there's already a user with this email signed up to PostHog,
        # either due to a reinstallation of the integration, or manual signup through PostHog itself.
        user = User.objects.filter(email=config.account.contact.email).first()
        user_created = False

        with transaction.atomic():
            try:
                if not user:
                    user = User.objects.create_user(
                        email=config.account.contact.email,
                        password=None,
                        first_name=config.account.contact.name or "",
                        is_staff=False,
                        is_email_verified=False,
                    )
                    user_created = True

                # Through Vercel we can only create new organizations, not use existing ones.
                # Note: We won't create a team here, that's done during Vercel resource creation.
                organization = Organization.objects.create(
                    name=config.account.name or f"Vercel Installation {installation_id}"
                )

                user.join(organization=organization, level=OrganizationMembership.Level.OWNER)

                OrganizationIntegration.objects.update_or_create(
                    organization=organization,
                    kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
                    integration_id=installation_id,
                    defaults={
                        "config": asdict(config),
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

        config = ResourceConfig(**resource_data)

        installation = VercelIntegration._get_installation(installation_id)
        organization: Organization = installation.organization

        team = Team.objects.create_with_data(
            initiating_user=installation.created_by or None,
            organization=organization,
            name=config.name,
            has_completed_onboarding_for={
                "product_analytics": True
            },  # Mark one product as onboarded to show quick start sidebar
        )

        if installation.created_by:
            ProductIntent.register(
                team=team,
                product_type="feature_flags",
                context="vercel integration",
                user=installation.created_by,
            )

            ProductIntent.register(
                team=team,
                product_type="experiments",
                context="vercel integration",
                user=installation.created_by,
            )

        resource = Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config=asdict(config),
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
    def get_resource(resource_id: str) -> dict[str, Any]:
        resource, installation = VercelIntegration._get_resource_with_installation(resource_id)
        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def update_resource(resource_id: str, resource_data: dict[str, Any]) -> dict[str, Any]:
        logger.info("Starting Vercel resource update", resource_id=resource_id)
        resource, installation = VercelIntegration._get_resource_with_installation(resource_id)

        # Validate the partial update data by merging with existing config
        updated_config = copy.deepcopy(resource.config)
        updated_config.update(resource_data)

        # Validate and store the merged config as dataclass
        validated_config = ResourceConfig(**updated_config)
        resource.config = asdict(validated_config)
        resource.save(update_fields=["config"])

        logger.info("Successfully updated Vercel resource", resource_id=resource_id)
        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def delete_resource(resource_id: str) -> None:
        logger.info("Starting Vercel resource deletion", resource_id=resource_id)
        resource, _ = VercelIntegration._get_resource_with_installation(resource_id)
        resource.delete()
        logger.info("Successfully deleted Vercel resource", resource_id=resource_id)

    @staticmethod
    def _build_resource_response(resource: Integration, installation: OrganizationIntegration) -> dict[str, Any]:
        billing_plans = VercelIntegration.get_vercel_plans()
        current_plan_id = installation.config.get("billing_plan_id", "free")  # TODO: Replace with billing service
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
                "value": absolute_uri(),
            },
        ]
