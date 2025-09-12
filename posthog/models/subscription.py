from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from dateutil.rrule import FR, MO, SA, SU, TH, TU, WE, rrule

from posthog.exceptions_capture import capture_exception
from posthog.jwt import PosthogJwtAudience, decode_jwt, encode_jwt
from posthog.utils import absolute_uri

# Copied from rrule as it is not exported
FREQNAMES = ["YEARLY", "MONTHLY", "WEEKLY", "DAILY", "HOURLY", "MINUTELY", "SECONDLY"]

UNSUBSCRIBE_TOKEN_EXP_DAYS = 30

RRULE_WEEKDAY_MAP = {
    "monday": MO,
    "tuesday": TU,
    "wednesday": WE,
    "thursday": TH,
    "friday": FR,
    "saturday": SA,
    "sunday": SU,
}


@dataclass
class SubscriptionResourceInfo:
    kind: str
    name: str
    url: str


class Subscription(models.Model):
    """
    Rather than re-invent the wheel, we are roughly following the iCalender format for recurring schedules
    https://dateutil.readthedocs.io/en/stable/rrule.html

    Also see https://jakubroztocil.github.io/rrule/ for a helpful visual demonstration
    """

    class SubscriptionTarget(models.TextChoices):
        EMAIL = "email"
        SLACK = "slack"
        WEBHOOK = "webhook"

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
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.CASCADE, null=True)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE, null=True)

    # Subscription type (email, slack etc.)
    title = models.CharField(max_length=100, null=True, blank=True)
    target_type = models.CharField(max_length=10, choices=SubscriptionTarget.choices)
    target_value = models.TextField()

    # Subscription delivery (related to rrule)
    frequency = models.CharField(max_length=10, choices=SubscriptionFrequency.choices)
    interval = models.IntegerField(default=1)
    count = models.IntegerField(null=True)
    byweekday: ArrayField = ArrayField(
        models.CharField(max_length=10, choices=SubscriptionByWeekDay.choices),
        null=True,
        blank=True,
        default=None,
    )
    bysetpos = models.IntegerField(null=True)
    start_date = models.DateTimeField()
    until_date = models.DateTimeField(null=True, blank=True)

    # Controlled field - next schedule as helper for
    next_delivery_date = models.DateTimeField(null=True, blank=True)

    # Meta
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)

    def save(self, *args, **kwargs) -> None:
        # Only if the schedule has changed do we update the next delivery date
        if not self.id or str(self._rrule) != str(self.rrule):
            self.set_next_delivery_date()
            if "update_fields" in kwargs:
                kwargs["update_fields"].append("next_delivery_date")
        super().save(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rrule = self.rrule

    @property
    def rrule(self):
        freq = FREQNAMES.index(self.frequency.upper())

        return rrule(
            freq=freq,
            count=self.count,
            interval=self.interval,
            dtstart=self.start_date,
            until=self.until_date,
            bysetpos=self.bysetpos if self.byweekday else None,
            byweekday=to_rrule_weekdays(self.byweekday) if self.byweekday else None,
        )

    def set_next_delivery_date(self, from_dt=None):
        # We never want next_delivery_date to be in the past
        now = timezone.now() + timedelta(minutes=15)  # Buffer of 15 minutes since we might run a bit early
        self.next_delivery_date = self.rrule.after(dt=max(from_dt or now, now), inc=False)

    @property
    def url(self):
        if self.insight:
            return absolute_uri(f"/insights/{self.insight.short_id}/subscriptions/{self.id}")
        elif self.dashboard:
            return absolute_uri(f"/dashboard/{self.dashboard_id}/subscriptions/{self.id}")
        return None

    @property
    def resource_info(self) -> Optional[SubscriptionResourceInfo]:
        if self.insight:
            return SubscriptionResourceInfo(
                "Insight",
                f"{self.insight.name or self.insight.derived_name}",
                self.insight.url,
            )
        elif self.dashboard:
            return SubscriptionResourceInfo("Dashboard", self.dashboard.name, self.dashboard.url)

        return None

    @property
    def summary(self):
        try:
            human_frequency = {
                "daily": "day",
                "weekly": "week",
                "monthly": "month",
                "yearly": "year",
            }[self.frequency]
            if self.interval > 1:
                human_frequency = f"{human_frequency}s"

            summary = f"sent every {str(self.interval) + ' ' if self.interval > 1 else ''}{human_frequency}"

            if self.byweekday and self.bysetpos:
                human_bysetpos = {
                    1: "first",
                    2: "second",
                    3: "third",
                    4: "fourth",
                    -1: "last",
                }[self.bysetpos]
                summary += (
                    f" on the {human_bysetpos} {self.byweekday[0].capitalize() if len(self.byweekday) == 1 else 'day'}"
                )
            return summary
        except KeyError as e:
            capture_exception(e)
            return "sent on a schedule"

    def get_analytics_metadata(self) -> dict[str, Any]:
        """
        Returns serialized information about the object for analytics reporting.
        """
        return {
            "id": self.id,
            "target_type": self.target_type,
            "num_emails_invited": len(self.target_value.split(",")) if self.target_type == "email" else None,
            "frequency": self.frequency,
            "interval": self.interval,
            "byweekday": self.byweekday,
            "bysetpos": self.bysetpos,
        }


@receiver(post_save, sender=Subscription, dispatch_uid="hook-subscription-saved")
def subscription_saved(sender, instance, created, raw, using, **kwargs):
    from posthog.event_usage import report_user_action

    if instance.created_by and instance.resource_info:
        event_name: str = f"{instance.resource_info.kind.lower()} subscription {'created' if created else 'updated'}"
        report_user_action(instance.created_by, event_name, instance.get_analytics_metadata())


def to_rrule_weekdays(weekday: Subscription.SubscriptionByWeekDay):
    return {RRULE_WEEKDAY_MAP.get(x) for x in weekday}


def get_unsubscribe_token(subscription: Subscription, email: str) -> str:
    return encode_jwt(
        {"id": subscription.id, "email": email},
        expiry_delta=timedelta(days=UNSUBSCRIBE_TOKEN_EXP_DAYS),
        audience=PosthogJwtAudience.UNSUBSCRIBE,
    )


def unsubscribe_using_token(token: str) -> Subscription:
    info = decode_jwt(token, audience=PosthogJwtAudience.UNSUBSCRIBE)
    subscription = Subscription.objects.get(pk=info["id"])

    emails = subscription.target_value.split(",")

    if info["email"] in emails:
        emails = [email for email in emails if email != info["email"]]

        subscription.target_value = ",".join(emails)

        if not emails:
            subscription.deleted = True

        subscription.save()

    return subscription
