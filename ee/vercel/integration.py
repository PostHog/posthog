from typing import Any
from django.conf import settings
from django.db import IntegrityError
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from rest_framework import exceptions
import structlog
from posthog.exceptions_capture import capture_exception

from posthog.models.integration import Integration
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.user import User
from posthog.models import ProductIntent
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from django.db import transaction
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.event_usage import report_user_signed_up
from posthog.utils import absolute_uri
from ee.vercel.client import VercelAPIClient

logger = structlog.get_logger(__name__)


class VercelIntegration:
    @staticmethod
    def _get_installation(installation_id: str) -> OrganizationIntegration:
        try:
            return OrganizationIntegration.objects.get(
                kind=Integration.IntegrationKind.VERCEL, integration_id=installation_id
            )
        except OrganizationIntegration.DoesNotExist:
            raise exceptions.NotFound("Installation not found")

    @staticmethod
    def _get_installation_for_organization(organization: Organization) -> OrganizationIntegration | None:
        try:
            return OrganizationIntegration.objects.get(
                organization=organization, kind=Integration.IntegrationKind.VERCEL
            )
        except OrganizationIntegration.DoesNotExist:
            return None

    @staticmethod
    def _get_access_token(installation: OrganizationIntegration) -> str | None:
        access_token = installation.config.get("credentials", {}).get("access_token")
        if not access_token:
            logger.exception("vercel_access_token_missing", installation_id=installation.integration_id)
        return access_token

    @staticmethod
    def _create_vercel_client(access_token: str) -> VercelAPIClient | None:
        try:
            return VercelAPIClient(bearer_token=access_token)
        except ValueError as e:
            logger.exception("vercel_client_creation_failed")
            capture_exception(e)
            return None

    @staticmethod
    def _setup_vercel_client_for_feature_flag(feature_flag: FeatureFlag) -> tuple[VercelAPIClient, str, str] | None:
        resource = VercelIntegration._get_vercel_resource_for_feature_flag(feature_flag)
        if not resource:
            logger.exception("vercel_resource_not_found", feature_flag_id=feature_flag.pk)
            return None

        installation = VercelIntegration._get_installation_for_organization(resource.team.organization)
        if not installation:
            logger.exception("vercel_installation_not_found", team_id=resource.team.id)
            return None

        access_token = VercelIntegration._get_access_token(installation)
        if not access_token:
            return None

        client = VercelIntegration._create_vercel_client(access_token)
        if not client:
            return None

        integration_config_id = installation.integration_id
        resource_id = str(resource.pk)

        return client, integration_config_id, resource_id

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
        logger.info("vercel_installation_upsert_started", installation_id=installation_id)

        with transaction.atomic():
            try:
                existing_installation = OrganizationIntegration.objects.get(
                    kind=Integration.IntegrationKind.VERCEL, integration_id=installation_id
                )
                organization = existing_installation.organization
                user = organization.members.filter(is_active=True).first()
                logger.info("vercel_installation_found_existing", installation_id=installation_id)
            except OrganizationIntegration.DoesNotExist:
                try:
                    user = User.objects.create_user(
                        email=payload["account"]["contact"]["email"],
                        password=None,
                        first_name=payload["account"]["contact"].get("name", ""),
                        is_staff=False,
                        is_email_verified=False,
                    )
                    organization = Organization.objects.create(
                        name=payload["account"].get("name", f"Vercel Installation {installation_id}")
                    )
                    Team.objects.create_with_data(initiating_user=user, organization=organization)
                    user.join(organization=organization, level=OrganizationMembership.Level.OWNER)
                    logger.info("vercel_installation_created_new", installation_id=installation_id)
                except IntegrityError as e:
                    logger.exception("vercel_installation_email_conflict", email=payload["account"]["contact"]["email"])
                    capture_exception(e)
                    raise exceptions.ValidationError(
                        {"email": "There is already an account with this email address."},
                        code="unique",
                    )

                report_user_signed_up(
                    user,
                    is_instance_first_user=False,
                    is_organization_first_user=True,
                    backend_processor="VercelInstallationViewSet",
                    user_analytics_metadata=user.get_analytics_metadata(),
                    org_analytics_metadata=organization.get_analytics_metadata(),
                    social_provider="vercel",
                    referral_source="vercel",
                )

        installation, created = OrganizationIntegration.objects.get_or_create(
            organization=organization,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=installation_id,
            defaults={
                "config": {
                    **payload,
                    "billing_plan_id": "free",
                },
                "created_by": user,
            },
        )

        if not created:
            installation.config = {
                **payload,
                "billing_plan_id": "free",
            }
            installation.save()

        logger.info("vercel_installation_created", installation_id=installation_id, organization_id=organization.id)

    @staticmethod
    def get_installation(installation_id: str) -> dict[str, Any]:
        installation = VercelIntegration._get_installation(installation_id)

        billing_plans = VercelIntegration.get_vercel_plans()
        current_plan_id = installation.config.get("billing_plan_id", "free")

        current_plan = next((plan for plan in billing_plans if plan["id"] == current_plan_id), None)
        return {
            "billingplan": current_plan,
        }

    @staticmethod
    def update_installation(installation_id: str, payload: dict[str, Any]) -> None:
        logger.info("vercel_installation_update_started", installation_id=installation_id)
        installation = VercelIntegration._get_installation(installation_id)

        installation.config.update(payload)
        installation.save(update_fields=["config"])

        logger.info("vercel_installation_updated", installation_id=installation_id)

    @staticmethod
    def delete_installation(installation_id: str) -> dict[str, Any]:
        logger.info("vercel_installation_delete_started", installation_id=installation_id)
        installation = VercelIntegration._get_installation(installation_id)
        installation.delete()

        is_dev = settings.DEBUG
        logger.info("vercel_installation_deleted", installation_id=installation_id, finalized=is_dev)
        return {"finalized": is_dev}

    @staticmethod
    def get_product_plans(product_slug: str) -> dict[str, Any]:
        if product_slug != "posthog":
            raise exceptions.NotFound("Product not found")

        return {"plans": VercelIntegration.get_vercel_plans()}

    @staticmethod
    def create_resource(installation_id: str, resource_data: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "vercel_resource_create_started", installation_id=installation_id, resource_name=resource_data.get("name")
        )
        installation = VercelIntegration._get_installation(installation_id)
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

        resource = Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config=resource_data,
            created_by=installation.created_by,
        )

        logger.info(
            "vercel_resource_created", installation_id=installation_id, resource_id=resource.pk, team_id=team.id
        )

        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def get_resource(resource_id: str, installation_id: str) -> dict[str, Any]:
        resource = Integration.objects.get(pk=resource_id, kind=Integration.IntegrationKind.VERCEL)
        installation = VercelIntegration._get_installation(installation_id)
        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def update_resource(resource_id: str, installation_id: str, resource_data: dict[str, Any]) -> dict[str, Any]:
        logger.info("vercel_resource_update_started", resource_id=resource_id, installation_id=installation_id)
        resource = Integration.objects.get(pk=resource_id, kind=Integration.IntegrationKind.VERCEL)
        installation = VercelIntegration._get_installation(installation_id)

        updated_config = resource.config.copy()
        updated_config.update(resource_data)
        resource.config = updated_config
        resource.save(update_fields=["config"])

        logger.info("vercel_resource_updated", resource_id=resource_id)
        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def delete_resource(resource_id: str) -> None:
        logger.info("vercel_resource_delete_started", resource_id=resource_id)
        try:
            resource = Integration.objects.get(pk=resource_id)
            resource.delete()
            logger.info("vercel_resource_deleted", resource_id=resource_id)
        except Integration.DoesNotExist:
            logger.exception("vercel_resource_not_found", resource_id=resource_id)
            raise exceptions.NotFound("Resource not found")

    @staticmethod
    def _build_resource_response(resource: Integration, installation: OrganizationIntegration) -> dict[str, Any]:
        billing_plans = VercelIntegration.get_vercel_plans()
        current_plan_id = installation.config.get("billing_plan_id", "free")
        current_plan = next((plan for plan in billing_plans if plan["id"] == current_plan_id), None)

        return {
            "id": str(resource.pk),  # TODO: Should this be resource.pk or resource.team.uuid
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
                "value": "https://app.posthog.com",
            },
        ]

    @staticmethod
    def sync_feature_flag_to_vercel(feature_flag: FeatureFlag, created: bool) -> None:
        setup_result = VercelIntegration._setup_vercel_client_for_feature_flag(feature_flag)
        if not setup_result:
            return

        client, integration_config_id, resource_id = setup_result
        vercel_item = VercelIntegration._convert_feature_flag_to_vercel_item(feature_flag)

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
        setup_result = VercelIntegration._setup_vercel_client_for_feature_flag(feature_flag)
        if not setup_result:
            return

        client, integration_config_id, resource_id = setup_result

        logger.info("vercel_feature_flag_delete_started", feature_flag_id=feature_flag.pk)
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
        else:
            logger.exception(
                "feature_flag_delete_failed",
                feature_flag_id=feature_flag.pk,
                integration_config_id=integration_config_id,
                resource_id=resource_id,
            )

    @staticmethod
    def _convert_feature_flag_to_vercel_item(feature_flag: FeatureFlag) -> dict:
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
    def _get_vercel_resource_for_feature_flag(feature_flag: FeatureFlag) -> Integration | None:
        try:
            return Integration.objects.get(team=feature_flag.team, kind=Integration.IntegrationKind.VERCEL)
        except Integration.DoesNotExist:
            return None


# TODO: Use jobs for these
@receiver(post_save, sender=FeatureFlag)
def update_resource_experimentation_item(sender, instance: FeatureFlag, created, **kwargs):
    VercelIntegration.sync_feature_flag_to_vercel(instance, created)


@receiver(post_delete, sender=FeatureFlag)
def delete_resource_experimentation_item(sender, instance: FeatureFlag, **kwargs):
    VercelIntegration.delete_feature_flag_from_vercel(instance)
