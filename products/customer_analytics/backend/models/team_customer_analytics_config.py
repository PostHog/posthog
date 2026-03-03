import logging

from django.db import models

from posthog.models import Team
from posthog.models.team.extensions import register_team_extension_signal

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


register_team_extension_signal(
    TeamCustomerAnalyticsConfig,
    defaults={"activity_event": DEFAULT_ACTIVITY_EVENT},
    logger=logger,
)
