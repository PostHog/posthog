import logging

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.schema import RevenueAnalyticsEventItem, RevenueAnalyticsGoal

from posthog.models.team import Team
from posthog.models.team.team import CURRENCY_CODE_CHOICES, DEFAULT_CURRENCY
from posthog.rbac.decorators import field_access_control

logger = logging.getLogger(__name__)


# Intentionally not inheriting from UUIDModel/UUIDTModel because we're using a OneToOneField
# and therefore using the exact same primary key as the Team model.
class TeamRevenueAnalyticsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    filter_test_accounts = field_access_control(models.BooleanField(default=False), "revenue_analytics", "editor")
    notified_first_sync = models.BooleanField(default=False, null=True)

    # Because we want to validate the schema for these fields, we'll have mangled DB fields/columns
    # that are then wrapped by schema-validation getters/setters
    _events = field_access_control(models.JSONField(default=list, db_column="events"), "revenue_analytics", "editor")
    _goals = field_access_control(
        models.JSONField(default=list, db_column="goals", null=True, blank=True), "revenue_analytics", "editor"
    )

    # DEPRECATED: Use `team.base_currency` instead
    base_currency = models.CharField(max_length=3, choices=CURRENCY_CODE_CHOICES, default=DEFAULT_CURRENCY)

    @property
    def events(self) -> list[RevenueAnalyticsEventItem]:
        return [RevenueAnalyticsEventItem.model_validate(event) for event in self._events or []]

    @events.setter
    def events(self, value: list[dict]) -> None:
        value = value or []
        try:
            dumped_value = [RevenueAnalyticsEventItem.model_validate(event).model_dump() for event in value]
            self._events = dumped_value
        except Exception as e:
            raise ValidationError(f"Invalid events schema: {str(e)}")

    @property
    def goals(self) -> list[RevenueAnalyticsGoal]:
        return [RevenueAnalyticsGoal.model_validate(goal) for goal in self._goals or []]

    @goals.setter
    def goals(self, value: list[dict]) -> None:
        value = value or []
        try:
            dumped_value = sorted(
                [RevenueAnalyticsGoal.model_validate(goal).model_dump() for goal in value],
                key=lambda x: x["due_date"],
            )
            self._goals = dumped_value
        except Exception as e:
            raise ValidationError(f"Invalid goals schema: {str(e)}")

    # `goals` arent included here because they aren't used for computations (yet)
    def to_cache_key_dict(self) -> dict:
        return {
            "base_currency": self.team.base_currency,
            "filter_test_accounts": self.filter_test_accounts,
            "events": [event.model_dump() for event in self.events],
        }


# This is best effort, we always attempt to create the config manually
# when accessing it via `Team.revenue_analytics_config`.
# In theory, this shouldn't ever fail, but it does fail in some tests cases
# so let's make it very forgiving
@receiver(post_save, sender=Team)
def create_team_revenue_analytics_config(sender, instance, created, **kwargs):
    try:
        if created:
            TeamRevenueAnalyticsConfig.objects.get_or_create(team=instance)
    except Exception as e:
        logger.warning(f"Error creating team revenue analytics config: {e}")
