import logging

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.models import Team

from products.customer_analytics.backend.constants import DEFAULT_ACTIVITY_EVENT

logger = logging.getLogger(__name__)


class TeamCustomerAnalyticsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    activity_event = models.JSONField(default=dict)
    signup_pageview_event = models.JSONField(default=dict)
    signup_event = models.JSONField(default=dict)
    subscription_event = models.JSONField(default=dict)
    payment_event = models.JSONField(default=dict)

    def to_cache_key_dict(self) -> dict:
        return {
            "activity_event": self.activity_event,
            "signup_pageview_event": self.signup_pageview_event,
            "signup_event": self.signup_event,
            "subscription_event": self.subscription_event,
            "payment_event": self.payment_event,
        }


@receiver(post_save, sender=Team)
def create_team_revenue_analytics_config(sender, instance, created, **kwargs):
    try:
        if created:
            TeamCustomerAnalyticsConfig.objects.get_or_create(
                team=instance, defaults={"activity_event": DEFAULT_ACTIVITY_EVENT}
            )
    except Exception as e:
        logger.warning(f"Error creating team customer analytics config: {e}")
