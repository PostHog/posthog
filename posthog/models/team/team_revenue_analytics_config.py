from django.db import models
from posthog.models.team import Team
from posthog.schema import CurrencyCode, RevenueAnalyticsEventItem
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)

# Django requires a list of tuples for choices
CURRENCY_CODE_CHOICES = [(code.value, code.value) for code in CurrencyCode]

# Intentionally asserting this here to guarantee we remember
# to rerun migrations when a new currency is added
# python manage.py makemigrations
assert len(CURRENCY_CODE_CHOICES) == 152


# Intentionally not inheriting from UUIDModel because we're using a OneToOneField
# and therefore using the exact same primary key as the Team model.
class TeamRevenueAnalyticsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)
    base_currency = models.CharField(max_length=3, choices=CURRENCY_CODE_CHOICES, default=CurrencyCode.USD.value)
    notified_first_sync = models.BooleanField(default=False, null=True)

    # Mangled field because we want the `events` getter/setter wrapper
    # to be able to validate the schema of the events
    _events = models.JSONField(default=list, db_column="events")

    @property
    def events(self) -> list[RevenueAnalyticsEventItem]:
        return [RevenueAnalyticsEventItem.model_validate(event) for event in self._events]

    @events.setter
    def events(self, value: list[dict]) -> None:
        value = value or []
        try:
            dumped_value = [RevenueAnalyticsEventItem.model_validate(event).model_dump() for event in value]
            self._events = dumped_value
        except Exception as e:
            raise ValidationError(f"Invalid events schema: {str(e)}")


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
