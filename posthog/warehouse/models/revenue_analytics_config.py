import logging

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.warehouse.types import ExternalDataSourceType

from .external_data_source import ExternalDataSource

logger = logging.getLogger(__name__)


# Intentionally not inheriting from UUIDModel/UUIDTModel because we're using a OneToOneField
# and therefore using the exact same primary key as the ExternalDataSource model.
class ExternalDataSourceRevenueAnalyticsConfig(models.Model):
    external_data_source = models.OneToOneField(ExternalDataSource, on_delete=models.CASCADE, primary_key=True)

    enabled = models.BooleanField(default=True)
    include_invoiceless_charges = models.BooleanField(default=True)


# This is best effort, we always attempt to create the config manually
# when accessing it via `Team.revenue_analytics_config`.
# In theory, this shouldn't ever fail, but it does fail in some tests cases
# so let's make it very forgiving
@receiver(post_save, sender=ExternalDataSource)
def create_external_data_source_revenue_analytics_config(sender, instance, created, **kwargs):
    try:
        if created:
            ExternalDataSourceRevenueAnalyticsConfig.objects.get_or_create(
                external_data_source=instance,
                defaults={
                    "enabled": instance.source_type == ExternalDataSourceType.STRIPE,
                },
            )
    except Exception as e:
        logger.warning(f"Error creating external data source revenue analytics config: {e}")
