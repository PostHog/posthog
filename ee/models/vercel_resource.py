from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
import structlog

from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.team.team import Team
from ee.models.vercel_installation import VercelInstallation
from posthog.models.utils import UpdatedMetaFields, UUIDModel
from posthog.utils import absolute_uri
from ee.vercel.client import VercelAPIClient

logger = structlog.get_logger(__name__)


class VercelResource(UpdatedMetaFields, UUIDModel):
    """
    Each Vercel Resource is connected to only one PostHog Project/Team.
    It also belongs to only one Vercel Installation.
    """

    team = models.OneToOneField(Team, on_delete=models.CASCADE)
    installation = models.ForeignKey(VercelInstallation, related_name="resources", on_delete=models.CASCADE)
    resource_id = models.CharField(max_length=255, unique=True)
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


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


def _get_vercel_resource_for_feature_flag(feature_flag: FeatureFlag) -> "VercelResource | None":
    """Get the Vercel resource for this team"""
    try:
        return VercelResource.objects.get(team=feature_flag.team)
    except VercelResource.DoesNotExist:
        return None


@receiver(post_save, sender=FeatureFlag)
def update_resource_experimentation_item(sender, instance: FeatureFlag, created, **kwargs):
    """
    Handle feature flag save events by syncing it as an experimentation item
    on the related resource in Vercel.
    """

    client = VercelAPIClient(bearer_token="mock_token")  # TODO: Get actual token from configuration/settings
    if not client:
        logger.error("vercel_client_unavailable", feature_flag_id=instance.pk)
        return

    resource = _get_vercel_resource_for_feature_flag(instance)
    if not resource:
        logger.debug("vercel_resource_not_found", feature_flag_id=instance.pk)
        return

    vercel_item = _convert_feature_flag_to_vercel_item(instance)
    integration_config_id = resource.installation.installation_id
    resource_id = resource.resource_id

    if created:
        success: bool = client.create_experimentation_items(
            integration_config_id=integration_config_id, resource_id=resource_id, items=[vercel_item]
        )
        if success:
            logger.info(
                "feature_flag_created_in_vercel",
                feature_flag_id=instance.pk,
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
            item_id=str(instance.pk),
            data=update_data,
        )
        if success:
            logger.info(
                "feature_flag_updated_in_vercel",
                feature_flag_id=instance.pk,
                integration_config_id=integration_config_id,
                resource_id=resource_id,
            )


@receiver(signal=post_delete, sender=FeatureFlag)
def delete_resource_experimentation_item(sender, instance: FeatureFlag, **kwargs):
    """
    Handle feature flag deletion by removing it as an experimentation item
    from the related resource in Vercel.
    """

    client = VercelAPIClient(bearer_token="mock_token")  # TODO: Get actual token from configuration/settings
    if not client:
        logger.error("vercel_client_unavailable", feature_flag_id=instance.pk)
        return

    resource = _get_vercel_resource_for_feature_flag(instance)
    if not resource:
        logger.debug("vercel_resource_not_found", feature_flag_id=instance.pk)
        return

    integration_config_id = resource.installation.installation_id
    resource_id = resource.resource_id

    success = client.delete_experimentation_item(
        integration_config_id=integration_config_id, resource_id=resource_id, item_id=str(instance.pk)
    )
    if success:
        logger.info(
            "feature_flag_deleted_from_vercel",
            feature_flag_id=instance.pk,
            integration_config_id=integration_config_id,
            resource_id=resource_id,
        )
