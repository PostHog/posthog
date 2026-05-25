from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Optional, cast

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from dateutil.rrule import DAILY, FR, MO, MONTHLY, SA, SU, TH, TU, WE, WEEKLY, YEARLY, rrule

from posthog.exceptions_capture import capture_exception
from posthog.jwt import PosthogJwtAudience, decode_jwt, encode_jwt
from posthog.models.utils import UUIDModel
from posthog.utils import absolute_uri

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

WEEKDAY_SET = {"monday", "tuesday", "wednesday", "thursday", "friday"}


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

    RRULE_FIELDS = {"frequency", "count", "interval", "start_date", "until_date", "bysetpos", "byweekday"}

    _FREQ_MAP: dict[str, int] = {
        SubscriptionFrequency.DAILY: DAILY,
        SubscriptionFrequency.WEEKLY: WEEKLY,
        SubscriptionFrequency.MONTHLY: MONTHLY,
        SubscriptionFrequency.YEARLY: YEARLY,
    }

    # Relations - i.e. WHAT are we exporting?
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    dashboard = models.ForeignKey("dashboards.Dashboard", on_delete=models.CASCADE, null=True)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE, null=True)
    dashboard_export_insights = models.ManyToManyField(
        "posthog.Insight",
        blank=True,
        related_name="subscriptions_dashboard_export",
    )
    integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=False,
    )

    # Subscription type (email, slack etc.)
    title = models.CharField(max_length=100, null=True, blank=True)
    target_type = models.CharField(max_length=10, choices=SubscriptionTarget)
    target_value = models.TextField()

    # Subscription delivery (related to rrule)
    frequency = models.CharField(max_length=10, choices=SubscriptionFrequency)
    interval = models.IntegerField(default=1)
    count = models.IntegerField(null=True)
    byweekday: ArrayField = ArrayField(
        models.CharField(max_length=10, choices=SubscriptionByWeekDay),
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

    # False when paused or auto-disabled because the delivery prerequisite is
    # permanently invalid (e.g. Slack integration disconnected).
    enabled = models.BooleanField(default=True)

    summary_enabled = models.BooleanField(default=False)
    summary_prompt_guide = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["integration"], name="posthog_sub_integration_idx"),
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only cache rrule if all required fields are loaded (not deferred).
        # The rrule property accesses multiple fields (frequency, count, interval, etc).
        # If ANY field is deferred, accessing it triggers refresh_from_db which creates
        # a new instance with OTHER fields deferred, causing infinite recursion.
        if not (self.get_deferred_fields() & self.RRULE_FIELDS):
            self._rrule = self.rrule

    def save(self, *args, **kwargs) -> None:
        # Only if the schedule has changed do we update the next delivery date
        # _rrule may not be set if object was loaded with deferred fields
        if not self.id or str(getattr(self, "_rrule", None)) != str(self.rrule):
            self.set_next_delivery_date()
            if "update_fields" in kwargs:
                kwargs["update_fields"].append("next_delivery_date")
        super().save(*args, **kwargs)

    @staticmethod
    def _build_rrule(
        *,
        frequency: str,
        start_date: Any,
        count: Any = None,
        interval: Any = None,
        until_date: Any = None,
        bysetpos: Any = None,
        byweekday: Any = None,
    ) -> rrule:
        freq = cast(Literal[0, 1, 2, 3, 4, 5, 6], Subscription._FREQ_MAP[frequency])
        return rrule(
            freq=freq,
            count=count,
            interval=interval,
            dtstart=start_date,
            until=until_date,
            bysetpos=bysetpos if byweekday else None,
            byweekday=to_rrule_weekdays(byweekday) if byweekday else None,
        )

    @staticmethod
    def _compute_next_delivery_date(*, from_dt: Optional[datetime] = None, **rrule_fields: Any) -> Optional[datetime]:
        # Buffer of 15 minutes since we might run a bit early — never schedule into the past.
        now = timezone.now() + timedelta(minutes=15)
        return Subscription._build_rrule(**rrule_fields).after(dt=max(from_dt or now, now), inc=False)

    @property
    def rrule(self) -> rrule:
        return self._build_rrule(**{f: getattr(self, f) for f in self.RRULE_FIELDS})

    def set_next_delivery_date(self, from_dt: Optional[datetime] = None) -> None:
        # Authoritative schedule — a client-side preview mirror lives in
        # frontend/src/lib/components/Subscriptions/utils.tsx (getNextDeliveryDate).
        self.next_delivery_date = self._compute_next_delivery_date(
            from_dt=from_dt, **{f: getattr(self, f) for f in self.RRULE_FIELDS}
        )

    @classmethod
    def project_next_delivery_date(
        cls, instance: Optional["Subscription"] = None, **overrides: Any
    ) -> Optional[datetime]:
        """What `next_delivery_date` would be for the rrule defined by `instance` fields
        (when given) layered with `overrides`, without persisting. Returns None on an
        exhausted rrule. Pass `instance` for PATCH validation, omit it for creates."""
        base = {f: getattr(instance, f) for f in cls.RRULE_FIELDS} if instance is not None else {}
        merged = {**base, **{k: v for k, v in overrides.items() if k in cls.RRULE_FIELDS}}
        if "frequency" not in merged or "start_date" not in merged:
            return None  # DRF field validation should reject before we get here.
        return cls._compute_next_delivery_date(**merged)

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
            return SubscriptionResourceInfo("Dashboard", self.dashboard.name or "Dashboard", self.dashboard.url)

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
                if len(self.byweekday) == 1:
                    day_label = self.byweekday[0].capitalize()
                elif set(self.byweekday) == WEEKDAY_SET:
                    day_label = "weekday"
                else:
                    day_label = "day"
                summary += f" on the {human_bysetpos} {day_label}"
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


class SubscriptionDelivery(UUIDModel):
    class Status(models.TextChoices):
        STARTING = "starting"
        COMPLETED = "completed"
        FAILED = "failed"
        SKIPPED = "skipped"

    subscription = models.ForeignKey("Subscription", on_delete=models.CASCADE, related_name="deliveries")
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    # Temporal correlation — workflow_id for debugging, idempotency_key for dedup.
    # idempotency_key is generated via temporalio.workflow.uuid4() which is deterministic
    # across activity retries (replay) but different across workflow retries.
    temporal_workflow_id = models.CharField(max_length=255)
    idempotency_key = models.CharField(max_length=255, unique=True)

    # Trigger context
    trigger_type = models.CharField(max_length=20)
    scheduled_at = models.DateTimeField(null=True)

    # Target snapshot (frozen at delivery time)
    target_type = models.CharField(max_length=10)
    target_value = models.TextField()

    # Content snapshot
    exported_asset_ids: ArrayField = ArrayField(models.IntegerField(), default=list)
    content_snapshot = models.JSONField(default=dict)

    # AI-generated summary sent in the delivery, when summary_enabled is on for the subscription.
    # None when no summary is attached.
    change_summary = models.TextField(null=True, blank=True)

    # Per-recipient delivery results
    recipient_results = models.JSONField(default=list)

    # Overall status and error (null when no error)
    # Shape: {"message": str, "type": str, ...} — extensible for stack traces, codes, etc.
    status = models.CharField(max_length=24, choices=Status, default=Status.STARTING)
    error = models.JSONField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_subscription_delivery"
        indexes = [
            models.Index(fields=["subscription", "-created_at"], name="posthog_subdel_sub_crtd"),
            models.Index(fields=["team", "-created_at"], name="posthog_subdel_team_crtd"),
        ]
        ordering = ["-created_at"]


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
