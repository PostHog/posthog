from django.db import models
from posthog.models.team import Team
from posthog.models.team.team import CURRENCY_CODE_CHOICES, DEFAULT_CURRENCY
from posthog.schema import RevenueAnalyticsEventItem, RevenueAnalyticsGoal
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)


# Intentionally not inheriting from UUIDModel because we're using a OneToOneField
# and therefore using the exact same primary key as the Team model.
class TeamRevenueAnalyticsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)
    base_currency = models.CharField(max_length=3, choices=CURRENCY_CODE_CHOICES, default=DEFAULT_CURRENCY)
    filter_test_accounts = models.BooleanField(default=False)
    notified_first_sync = models.BooleanField(default=False, null=True)

    # Mangled fields incoming:
    # Because we want to validate the schema for these fields, we'll have mangled DB fields/columns
    # that are then wrapped by schema-validation getters/setters
    _events = models.JSONField(default=list, db_column="events")
    _goals = models.JSONField(default=list, db_column="goals", null=True, blank=True)

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
