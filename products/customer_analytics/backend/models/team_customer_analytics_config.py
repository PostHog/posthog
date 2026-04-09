import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal
from posthog.rbac.decorators import field_access_control

from products.customer_analytics.backend.constants import DEFAULT_ACTIVITY_EVENT

logger = logging.getLogger(__name__)


class TeamCustomerAnalyticsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    activity_event = field_access_control(models.JSONField(default=dict), "project", "admin")
    signup_pageview_event = field_access_control(models.JSONField(default=dict), "project", "admin")
    signup_event = field_access_control(models.JSONField(default=dict), "project", "admin")
    subscription_event = field_access_control(models.JSONField(default=dict), "project", "admin")
    payment_event = field_access_control(models.JSONField(default=dict), "project", "admin")

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
