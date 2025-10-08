import logging

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.models.team import Team

logger = logging.getLogger(__name__)


# Intentionally not inheriting from UUIDModel/UUIDTModel because we're using a OneToOneField
# and therefore using the exact same primary key as the Team model.
class TeamDataWarehouseConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    revenue_analytics_package_view_enabled_at = models.DateTimeField(null=True)

    def to_cache_key_dict(self) -> dict:
        return {
            "revenue_analytics_package_view_enabled_at": self.revenue_analytics_package_view_enabled_at,
        }


# This is best effort, we always attempt to create the config manually
# when accessing it via `Team.data_warehouse_config`.
# In theory, this shouldn't ever fail, but it does fail in some tests cases
# so let's make it very forgiving
@receiver(post_save, sender=Team)
def create_team_data_warehouse_config(sender, instance, created, **kwargs):
    try:
        if created:
            TeamDataWarehouseConfig.objects.get_or_create(team=instance)
    except Exception as e:
        logger.warning(f"Error creating team data warehouse config: {e}")
