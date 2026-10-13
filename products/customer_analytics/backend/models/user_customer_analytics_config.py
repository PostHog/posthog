from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UpdatedMetaFields, UUIDModel


class UserCustomerAnalyticsConfig(TeamScopedRootMixin, UUIDModel, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    pinned_custom_property_definition_ids = ArrayField(models.UUIDField(), default=list)
    properties = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user"],
                name="unique_user_customer_analytics_config_per_team",
            )
        ]
