from dateutil.rrule import FREQNAMES, rrule
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone


class Subscription(models.Model):
    """
    Rather than re-invent the wheel, we are roughly following the iCalender format for recurring schedules
    https://dateutil.readthedocs.io/en/stable/rrule.html

    Also see https://jakubroztocil.github.io/rrule/ for a helpful visual demonstration
    """

    class SubscriptionTarget(models.TextChoices):
        EMAIL = "email"
        # SLACK = "slack"

    class SubscriptionFrequency(models.TextChoices):
        DAILY = "daily"
        WEEKLY = "weekly"
        MONTHLY = "monthly"
        YEARLY = "yearly"

    class SubscriptionByWeekDay(models.TextChoices):
        MONDAY = "monday"
        TUESDAY = "tuesday"
        WEDNESDAY = "wednesday"
        THURSDAY = "thursday"
        FRIDAY = "friday"
        SATURDAY = "saturday"
        SUNDAY = "sunday"

    # Relations - i.e. WHAT are we exporting?
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.CASCADE, null=True)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE, null=True)

    # Subscription type (email, slack etc.)
    target_type: models.CharField = models.CharField(max_length=10, choices=SubscriptionTarget.choices)
    target_value: models.CharField = models.CharField(max_length=65535)

    # Subscription delivery (related to rrule)
    frequency: models.CharField = models.CharField(max_length=10, choices=SubscriptionFrequency.choices)
    interval: models.IntegerField = models.IntegerField(default=1)
    count: models.IntegerField = models.IntegerField(null=True)
    byweekday: ArrayField = ArrayField(
        models.CharField(max_length=10, choices=SubscriptionByWeekDay.choices), null=True, blank=True, default=None
    )
    bysetpos: models.IntegerField = models.IntegerField(null=True)
    start_date: models.DateTimeField = models.DateTimeField()
    until_date: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    # Controlled field - next schedule as helper for
    next_delivery_date: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    # Meta
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)

    @property
    def rrule(self):
        freq = FREQNAMES.index(self.frequency.upper())
        return rrule(
            freq=freq,
            count=self.count,
            interval=self.interval,
            dtstart=self.start_date,
            until=self.until_date,
            bysetpos=self.bysetpos,
            byweekday=[x[:2].upper() for x in self.byweekday] if self.byweekday else None,
        )

    @property
    def title(self):
        return f"Sent every {self.interval} {self.frequency}"

    def set_next_delivery_date(self, from_dt=None):
        self.next_delivery_date = self.rrule.after(dt=from_dt or timezone.now(), inc=False)

    def save(self, *args, **kwargs) -> None:
        self.set_next_delivery_date()
        super(Subscription, self).save(*args, **kwargs)

    @property
    def url(self):
        return f"{settings.SITE_URL}/insights/{self.insight.short_id}/subscriptions/{self.id}"
