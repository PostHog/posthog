import copy
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify

import structlog
from rest_framework import exceptions

from posthog.event_usage import report_user_signed_up
from posthog.exceptions_capture import capture_exception
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.product_intent import ProductIntent
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import absolute_uri

from ee.vercel.client import VercelAPIClient

logger = structlog.get_logger(__name__)

VercelItemType = Literal["flag", "experiment"]


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


@dataclass
class VercelSetupResult:
    client: VercelAPIClient
    integration_config_id: str
    resource_id: str


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

        logger.info(
            "Starting Vercel installation upsert process", installation_id=installation_id, integration="vercel"
        )

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
            logger.info("Vercel installation updated", installation_id=installation_id, integration="vercel")
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

                logger.info("Created new Vercel installation", installation_id=installation_id, integration="vercel")
            except IntegrityError as e:
                capture_exception(e)
                logger.exception(
                    "Failed to create Vercel installation", installation_id=installation_id, integration="vercel"
                )
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
            "Successfully created Vercel installation",
            installation_id=installation_id,
            organization_id=organization.id,
            integration="vercel",
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
        logger.info("Starting Vercel installation update", installation_id=installation_id, integration="vercel")

        # TODO: Implement billing plan update logic here, awaiting billing service implementation.

        logger.info("Successfully updated Vercel installation", installation_id=installation_id, integration="vercel")

    @staticmethod
    def delete_installation(installation_id: str) -> dict[str, Any]:
        logger.info("Starting Vercel installation deletion", installation_id=installation_id, integration="vercel")
        installation = VercelIntegration._get_installation(installation_id)
        installation.delete()
        is_dev = settings.DEBUG
        logger.info(
            "Successfully deleted Vercel installation",
            installation_id=installation_id,
            finalized=is_dev,
            integration="vercel",
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
            integration="vercel",
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
            integration="vercel",
        )

        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def get_resource(resource_id: str) -> dict[str, Any]:
        resource, installation = VercelIntegration._get_resource_with_installation(resource_id)
        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def update_resource(resource_id: str, resource_data: dict[str, Any]) -> dict[str, Any]:
        logger.info("Starting Vercel resource update", resource_id=resource_id, integration="vercel")
        resource, installation = VercelIntegration._get_resource_with_installation(resource_id)

        updated_config = copy.deepcopy(resource.config)
        updated_config.update(resource_data)

        validated_config = ResourceConfig(**updated_config)
        resource.config = asdict(validated_config)
        resource.save(update_fields=["config"])

        logger.info("Successfully updated Vercel resource", resource_id=resource_id, integration="vercel")
        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def delete_resource(resource_id: str) -> None:
        logger.info("Starting Vercel resource deletion", resource_id=resource_id, integration="vercel")
        resource, _ = VercelIntegration._get_resource_with_installation(resource_id)
        resource.delete()
        logger.info("Successfully deleted Vercel resource", resource_id=resource_id, integration="vercel")

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

    @staticmethod
    def _get_vercel_resource_for_team(team: Team) -> Integration | None:
        try:
            return Integration.objects.get(team=team, kind=Integration.IntegrationKind.VERCEL)
        except Integration.DoesNotExist:
            return None

    @staticmethod
    def _get_installation_for_organization(organization: Organization) -> OrganizationIntegration | None:
        try:
            return OrganizationIntegration.objects.get(
                organization=organization, kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL
            )
        except OrganizationIntegration.DoesNotExist:
            return None

    @staticmethod
    def _get_access_token(installation: OrganizationIntegration) -> str | None:
        access_token = installation.config.get("credentials", {}).get("access_token")
        if not access_token:
            logger.exception(
                "Missing access token for Vercel installation",
                installation_id=installation.integration_id,
                integration="vercel",
            )
        return access_token

    @staticmethod
    def _create_vercel_client(access_token: str) -> VercelAPIClient | None:
        try:
            return VercelAPIClient(bearer_token=access_token)
        except ValueError as e:
            logger.exception("Failed to create Vercel API client", integration="vercel")
            capture_exception(e)
            return None

    @staticmethod
    def _setup_vercel_client_for_team(team: Team) -> VercelSetupResult | None:
        resource = VercelIntegration._get_vercel_resource_for_team(team)
        if not resource:
            logger.debug("Vercel resource not found for team", team_id=team.id, integration="vercel")
            return None

        installation = VercelIntegration._get_installation_for_organization(team.organization)
        if not installation:
            logger.debug(
                "Vercel installation not found for organization",
                team_id=team.pk,
                organization_id=team.organization.pk,
                integration="vercel",
            )
            return None

        access_token = VercelIntegration._get_access_token(installation)
        if not access_token:
            logger.exception(
                "Failed to get access token for Vercel installation",
                installation_id=installation.integration_id,
                team_id=team.pk,
                integration="vercel",
            )
            return None

        client = VercelIntegration._create_vercel_client(access_token)
        if not client:
            logger.exception(
                "Failed to create Vercel API client",
                installation_id=installation.integration_id,
                team_id=team.pk,
                integration="vercel",
            )
            return None

        integration_config_id = installation.integration_id
        if not integration_config_id:
            logger.exception(
                "Missing integration_id in installation",
                installation_id=installation.pk,
                team_id=team.pk,
                integration="vercel",
            )
            return None

        resource_id = str(resource.pk)

        logger.debug(
            "Successfully set up Vercel client",
            team_id=team.pk,
            integration_config_id=integration_config_id,
            resource_id=resource_id,
            integration="vercel",
        )
        return VercelSetupResult(
            client=client,
            integration_config_id=integration_config_id,
            resource_id=resource_id,
        )

    @staticmethod
    def _get_vercel_item_id(item_type: VercelItemType, item_id: str | int) -> str:
        return f"{item_type}_{item_id}"

    @staticmethod
    def _sync_item_to_vercel(
        team: Team,
        item_type: VercelItemType,
        item_pk: str | int,
        vercel_item: dict,
        created: bool,
    ) -> None:
        setup_result = VercelIntegration._setup_vercel_client_for_team(team)
        if not setup_result:
            return

        item_id = VercelIntegration._get_vercel_item_id(item_type, item_pk)

        if created:
            result = setup_result.client.create_experimentation_items(
                integration_config_id=setup_result.integration_config_id,
                resource_id=setup_result.resource_id,
                items=[vercel_item],
            )
            if result.success:
                logger.info(
                    f"{item_type} created in Vercel",
                    item_id=item_id,
                    integration_config_id=setup_result.integration_config_id,
                    resource_id=setup_result.resource_id,
                    integration="vercel",
                )
            else:
                logger.exception(
                    f"Failed to create {item_type} in Vercel",
                    item_id=item_id,
                    error=result.error,
                    integration="vercel",
                )
        else:
            result = setup_result.client.update_experimentation_item(
                integration_config_id=setup_result.integration_config_id,
                resource_id=setup_result.resource_id,
                item_id=item_id,
                data=vercel_item,
            )
            if result.success:
                logger.info(
                    f"{item_type} updated in Vercel",
                    item_id=item_id,
                    integration_config_id=setup_result.integration_config_id,
                    resource_id=setup_result.resource_id,
                    integration="vercel",
                )
            else:
                logger.exception(
                    f"Failed to update {item_type} in Vercel",
                    item_id=item_id,
                    error=result.error,
                    integration="vercel",
                )

    @staticmethod
    def sync_feature_flag_to_vercel(feature_flag: FeatureFlag, created: bool) -> None:
        vercel_item = VercelIntegration._convert_feature_flag_to_vercel_item(feature_flag, created)
        VercelIntegration._sync_item_to_vercel(
            team=feature_flag.team,
            item_type="flag",
            item_pk=feature_flag.pk,
            vercel_item=vercel_item,
            created=created,
        )

    @staticmethod
    def _delete_item_from_vercel(team: Team, item_type: VercelItemType, item_id: str) -> None:
        setup_result = VercelIntegration._setup_vercel_client_for_team(team)
        if not setup_result:
            return

        logger.debug(f"Starting Vercel {item_type} deletion", item_id=item_id, integration="vercel")
        result = setup_result.client.delete_experimentation_item(
            integration_config_id=setup_result.integration_config_id,
            resource_id=setup_result.resource_id,
            item_id=item_id,
        )
        if result.success:
            logger.info(
                f"{item_type} deleted from Vercel",
                item_id=item_id,
                integration_config_id=setup_result.integration_config_id,
                resource_id=setup_result.resource_id,
                integration="vercel",
            )
        else:
            logger.exception(
                f"Failed to delete {item_type} from Vercel",
                item_id=item_id,
                integration_config_id=setup_result.integration_config_id,
                resource_id=setup_result.resource_id,
                error=result.error,
                integration="vercel",
            )

    @staticmethod
    def delete_feature_flag_from_vercel(feature_flag: FeatureFlag) -> None:
        VercelIntegration._delete_item_from_vercel(
            team=feature_flag.team,
            item_type="flag",
            item_id=VercelIntegration._get_vercel_item_id("flag", feature_flag.pk),
        )

    @staticmethod
    def sync_experiment_to_vercel(experiment: Experiment, created: bool) -> None:
        vercel_item = VercelIntegration._convert_experiment_to_vercel_item(experiment, created)
        VercelIntegration._sync_item_to_vercel(
            team=experiment.team,
            item_type="experiment",
            item_pk=experiment.pk,
            vercel_item=vercel_item,
            created=created,
        )

    @staticmethod
    def delete_experiment_from_vercel(experiment: Experiment) -> None:
        VercelIntegration._delete_item_from_vercel(
            team=experiment.team,
            item_type="experiment",
            item_id=VercelIntegration._get_vercel_item_id("experiment", experiment.pk),
        )

    @staticmethod
    def _convert_feature_flag_to_vercel_item(feature_flag: FeatureFlag, created: bool) -> dict:
        return {
            **({"id": VercelIntegration._get_vercel_item_id("flag", feature_flag.pk)} if created else {}),
            "slug": feature_flag.key,
            "origin": absolute_uri(f"/project/{feature_flag.team.id}/feature_flags/{feature_flag.pk}"),
            "category": "flag",
            "name": feature_flag.key,
            "description": feature_flag.name,
            "isArchived": feature_flag.deleted,
            "createdAt": int(feature_flag.created_at.timestamp() * 1000),
            "updatedAt": int(timezone.now().timestamp() * 1000),
        }

    @staticmethod
    def _convert_experiment_to_vercel_item(experiment: Experiment, created: bool) -> dict:
        return {
            **({"id": VercelIntegration._get_vercel_item_id("experiment", experiment.pk)} if created else {}),
            "slug": slugify(experiment.name) or f"experiment-{experiment.pk}",
            "origin": absolute_uri(f"/project/{experiment.team.id}/experiments/{experiment.pk}"),
            "category": "experiment",
            "name": experiment.name,
            "description": experiment.description or "",
            "isArchived": experiment.archived or experiment.deleted,
            "createdAt": int(experiment.created_at.timestamp() * 1000),
            "updatedAt": int(experiment.updated_at.timestamp() * 1000),
        }


def _safe_vercel_sync(operation_name: str, item_id: str | int, team: Team, sync_func: Callable[[], None]) -> None:
    """
    Safety wrapper for Vercel sync operations triggered by Django signals.

    Django signals run synchronously within the same database transaction as the save/delete operation.
    Without this wrapper, any network failure or API error from Vercel would cause the entire database operation to fail,
    blocking users from saving or deleting their feature flags and experiments.

    Operations are silently skipped if Vercel integration is not configured and
    exceptions are caught and logged rather than bubbling up to the caller.
    """
    if not VercelIntegration._get_vercel_resource_for_team(team):
        return

    try:
        sync_func()
    except Exception as e:
        logger.exception(
            f"Failed to {operation_name}",
            item_id=item_id,
            integration="vercel",
        )
        capture_exception(e)


@receiver(post_save, sender=FeatureFlag)
def sync_feature_flag_experimentation_item(sender, instance: FeatureFlag, created, **kwargs):
    if instance.deleted:
        _safe_vercel_sync(
            "delete feature flag from Vercel",
            instance.pk,
            instance.team,
            lambda: VercelIntegration.delete_feature_flag_from_vercel(instance),
        )
    else:
        _safe_vercel_sync(
            "sync feature flag to Vercel",
            instance.pk,
            instance.team,
            lambda: VercelIntegration.sync_feature_flag_to_vercel(instance, created),
        )


@receiver(post_delete, sender=FeatureFlag)
def delete_resource_experimentation_item(sender, instance: FeatureFlag, **kwargs):
    _safe_vercel_sync(
        "delete feature flag from Vercel",
        instance.pk,
        instance.team,
        lambda: VercelIntegration.delete_feature_flag_from_vercel(instance),
    )


@receiver(post_save, sender=Experiment)
def sync_experiment_experimentation_item(sender, instance: Experiment, created, **kwargs):
    if instance.deleted:
        _safe_vercel_sync(
            "delete experiment from Vercel",
            instance.pk,
            instance.team,
            lambda: VercelIntegration.delete_experiment_from_vercel(instance),
        )
    else:
        _safe_vercel_sync(
            "sync experiment to Vercel",
            instance.pk,
            instance.team,
            lambda: VercelIntegration.sync_experiment_to_vercel(instance, created),
        )


@receiver(post_delete, sender=Experiment)
def delete_experiment_experimentation_item(sender, instance: Experiment, **kwargs):
    _safe_vercel_sync(
        "delete experiment from Vercel",
        instance.pk,
        instance.team,
        lambda: VercelIntegration.delete_experiment_from_vercel(instance),
    )
