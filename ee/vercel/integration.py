from typing import Any
from django.conf import settings
from django.db import IntegrityError
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from rest_framework import exceptions, serializers
import structlog

from posthog.models.integration import Integration
from posthog.models.user import User
from posthog.models import ProductIntent
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.event_usage import report_user_signed_up
from posthog.utils import absolute_uri
from ee.models.vercel.vercel_installation import VercelInstallation
from ee.models.vercel.vercel_resource import VercelResource
from ee.vercel.client import VercelAPIClient

logger = structlog.get_logger(__name__)


class VercelIntegration:
    integration: Integration
    # organization_integration: OrganizationIntegration

    @staticmethod
    def get_vercel_plans() -> list[dict[str, Any]]:
        """Get PostHog plans formatted for Vercel Marketplace"""
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
        """Create or update a Vercel installation"""
        try:
            # TODO: Not sure if this is the best move because users might be confused
            # by the default project created here and their "Resource" project.
            organization, _, user = User.objects.bootstrap(
                is_staff=False,
                is_email_verified=False,
                role_at_organization="admin",
                email=payload["account"]["contact"]["email"],
                first_name=payload["account"]["contact"].get("name", ""),
                organization_name=payload["account"].get("name", f"Vercel Installation {installation_id}"),
                password=None,  # SSO instead of password. Users will still be able to reset their password.
            )
        except IntegrityError:
            raise exceptions.ValidationError(
                {"email": "There is already an account with this email address."},
                code="unique",
            )

        report_user_signed_up(
            user,
            is_instance_first_user=False,
            is_organization_first_user=True,  # Always true because we're always creating a new organization
            backend_processor="VercelInstallationViewSet",
            user_analytics_metadata=user.get_analytics_metadata(),
            org_analytics_metadata=user.organization.get_analytics_metadata() if user.organization else None,
            social_provider="vercel",
            referral_source="vercel",
        )

        VercelInstallation.objects.create(
            installation_id=installation_id,
            organization=organization,
            upsert_data=payload,
            # If the provider is using installation-level billing plans,
            # a default plan must be assigned in provider systems (default "free")
            billing_plan_id="free",
        )

    @staticmethod
    def get_installation(installation_id: str) -> dict[str, Any]:
        """Get installation details with billing plan"""
        installation = VercelInstallation.objects.get(installation_id=installation_id)

        billing_plans = VercelIntegration.get_vercel_plans()
        current_plan_id = installation.billing_plan_id

        current_plan = next((plan for plan in billing_plans if plan["id"] == current_plan_id), None)
        return {
            "billingplan": current_plan,
        }

    @staticmethod
    def update_installation(installation_id: str, payload: dict[str, Any]) -> None:
        """Update an existing installation"""
        try:
            installation = VercelInstallation.objects.get(installation_id=installation_id)
        except VercelInstallation.DoesNotExist:
            raise exceptions.NotFound("Installation not found")

        # TODO: Handle billing plan updates

        installation.upsert_data = payload
        installation.save(update_fields=["upsert_data"])

    @staticmethod
    def delete_installation(installation_id: str) -> dict[str, Any]:
        """Delete an installation"""
        try:
            installation = VercelInstallation.objects.get(installation_id=installation_id)
        except VercelInstallation.DoesNotExist:
            raise exceptions.NotFound("Installation not found")

        installation.delete()

        # In production, installation stays in "delete pending" state for 24 hours for invoicing
        is_dev = settings.DEBUG
        return {"finalized": is_dev}

    @staticmethod
    def get_product_plans(product_slug: str) -> dict[str, Any]:
        """Get plans for a specific product"""
        if product_slug != "posthog":
            raise exceptions.NotFound("Product not found")

        return {"plans": VercelIntegration.get_vercel_plans()}

    @staticmethod
    def create_resource(installation_id: str, resource_data: dict[str, Any]) -> dict[str, Any]:
        """Create a new resource for an installation"""
        installation = VercelInstallation.objects.get(installation_id=installation_id)
        organization: Organization = installation.organization

        team = Team.objects.create_with_data(
            initiating_user=None,
            organization=organization,
            name=resource_data["name"],
            has_completed_onboarding_for={
                "product_analytics": True
            },  # Mark one product as onboarded to show activation sidebar
        )

        ProductIntent.objects.create(
            team=team,
            product_type="feature_flags",
            contexts={"vercel native integration": 1},
        )

        ProductIntent.objects.create(
            team=team,
            product_type="experiments",
            contexts={"vercel native integration": 1},
        )

        resource: VercelResource = VercelResource.objects.create(
            team=team,
            installation=installation,
            config=resource_data,
        )

        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def get_resource(resource_id: str, installation_id: str) -> dict[str, Any]:
        """Get resource details"""
        resource = VercelResource.objects.get(pk=resource_id)
        installation = VercelInstallation.objects.get(installation_id=installation_id)
        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def update_resource(resource_id: str, installation_id: str, resource_data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing resource"""
        resource = VercelResource.objects.get(pk=resource_id)
        installation = VercelInstallation.objects.get(installation_id=installation_id)

        updated_config = resource.config.copy()
        updated_config.update(resource_data)
        resource.config = updated_config
        resource.save(update_fields=["config"])

        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def delete_resource(resource_id: str) -> None:
        """Delete a resource"""
        # TODO: Implement resource deletion logic
        raise serializers.MethodNotAllowed("DELETE")

    @staticmethod
    def _build_resource_response(resource: VercelResource, installation: VercelInstallation) -> dict[str, Any]:
        """Build the standard resource response data"""
        billing_plans = VercelIntegration.get_vercel_plans()
        current_plan_id = installation.billing_plan_id
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
        """Build the secrets array for the resource response"""
        return [
            {
                "name": "POSTHOG_PROJECT_API_KEY",
                "value": team.api_token,
            },
            {
                "name": "POSTHOG_HOST",
                "value": "https://app.posthog.com",
            },
        ]

    @staticmethod
    def sync_feature_flag_to_vercel(feature_flag: FeatureFlag, created: bool) -> None:
        """
        Sync a feature flag to Vercel as an experimentation item.
        Called from Django signal handlers.
        """
        resource = VercelIntegration._get_vercel_resource_for_feature_flag(feature_flag)
        if not resource:
            logger.debug("vercel_resource_not_found", feature_flag_id=feature_flag.pk)
            return

        access_token = resource.installation.upsert_data.get("credentials", {}).get("access_token")
        if not access_token:
            logger.error("vercel_access_token_unavailable", feature_flag_id=feature_flag.pk)
            return

        try:
            client = VercelAPIClient(bearer_token=access_token)
        except ValueError:
            logger.exception("vercel_client_initialization_failed", feature_flag_id=feature_flag.pk)
            return

        vercel_item = VercelIntegration._convert_feature_flag_to_vercel_item(feature_flag)
        integration_config_id = resource.installation.installation_id
        resource_id = resource.resource_id

        if created:
            success: bool = client.create_experimentation_items(
                integration_config_id=integration_config_id, resource_id=resource_id, items=[vercel_item]
            )
            if success:
                logger.info(
                    "feature_flag_created_in_vercel",
                    feature_flag_id=feature_flag.pk,
                    integration_config_id=integration_config_id,
                    resource_id=resource_id,
                )
        else:
            update_data = {
                "slug": vercel_item["slug"],
                "origin": vercel_item["origin"],
                "name": vercel_item["name"],
                "category": vercel_item["category"],
                "description": vercel_item["description"],
                "isArchived": vercel_item["isArchived"],
            }
            success = client.update_experimentation_item(
                integration_config_id=integration_config_id,
                resource_id=resource_id,
                item_id=str(feature_flag.pk),
                data=update_data,
            )
            if success:
                logger.info(
                    "feature_flag_updated_in_vercel",
                    feature_flag_id=feature_flag.pk,
                    integration_config_id=integration_config_id,
                    resource_id=resource_id,
                )

    @staticmethod
    def delete_feature_flag_from_vercel(feature_flag: FeatureFlag) -> None:
        """
        Delete a feature flag from Vercel experimentation items.
        Called from Django signal handlers.
        """
        resource = VercelIntegration._get_vercel_resource_for_feature_flag(feature_flag)
        if not resource:
            logger.debug("vercel_resource_not_found", feature_flag_id=feature_flag.pk)
            return

        access_token = resource.installation.upsert_data.get("credentials", {}).get("access_token")
        if not access_token:
            logger.error("vercel_access_token_unavailable", feature_flag_id=feature_flag.pk)
            return

        try:
            client = VercelAPIClient(bearer_token=access_token)
        except ValueError:
            logger.exception("vercel_client_initialization_failed", feature_flag_id=feature_flag.pk)
            return

        integration_config_id = resource.installation.installation_id
        resource_id = resource.resource_id

        success = client.delete_experimentation_item(
            integration_config_id=integration_config_id, resource_id=resource_id, item_id=str(feature_flag.pk)
        )
        if success:
            logger.info(
                "feature_flag_deleted_from_vercel",
                feature_flag_id=feature_flag.pk,
                integration_config_id=integration_config_id,
                resource_id=resource_id,
            )

    @staticmethod
    def _convert_feature_flag_to_vercel_item(feature_flag: FeatureFlag) -> dict:
        """Convert PostHog FeatureFlag to Vercel experimentation item format"""
        return {
            "id": str(feature_flag.pk),
            "slug": feature_flag.key,
            "origin": absolute_uri(f"/project/{feature_flag.team.id}/feature_flags/{feature_flag.pk}"),
            "category": "flag",
            "name": feature_flag.key,
            "description": feature_flag.name,
            "isArchived": not feature_flag.deleted,
            "createdAt": feature_flag.created_at.timestamp(),
        }

    @staticmethod
    def _get_vercel_resource_for_feature_flag(feature_flag: FeatureFlag) -> VercelResource | None:
        """Get the Vercel resource for this team"""
        try:
            return VercelResource.objects.get(team=feature_flag.team)
        except VercelResource.DoesNotExist:
            return None


# TODO: Use jobs for these
@receiver(post_save, sender=FeatureFlag)
def update_resource_experimentation_item(sender, instance: FeatureFlag, created, **kwargs):
    """
    Handle feature flag save events by syncing it as an experimentation item
    on the related resource in Vercel.
    """
    VercelIntegration.sync_feature_flag_to_vercel(instance, created)


@receiver(post_delete, sender=FeatureFlag)
def delete_resource_experimentation_item(sender, instance: FeatureFlag, **kwargs):
    """
    Handle feature flag deletion by removing it as an experimentation item
    from the related resource in Vercel.
    """
    VercelIntegration.delete_feature_flag_from_vercel(instance)
