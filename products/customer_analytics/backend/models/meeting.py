from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class MeetingStatus(models.TextChoices):
    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    CANCELLED = "cancelled"


class MeetingResponseStatus(models.TextChoices):
    NEEDS_ACTION = "needs_action"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    TENTATIVE = "tentative"


class Meeting(TeamScopedRootMixin, UUIDModel):
    """A calendar meeting synced from a connected employee calendar.

    One row per real-world meeting: copies of the same event on several synced
    calendars share an iCalUID (RFC 5545) and collapse into one row. Instances of
    a recurring series also share the series iCalUID, so `recurrence_instance_id`
    (the instance's original start slot) disambiguates them — it stays stable when
    a single instance is rescheduled, unlike the start time itself.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    account = models.ForeignKey(
        "customer_analytics.Account", on_delete=models.SET_NULL, null=True, blank=True, related_name="meetings"
    )

    ical_uid = models.CharField(max_length=1024)
    recurrence_instance_id = models.CharField(max_length=64, default="", blank=True)

    title = models.TextField(default="", blank=True)
    description = models.TextField(default="", blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    organizer_email = models.CharField(max_length=400, default="", blank=True)
    # Google Meet meeting code — the join key to conference records (and later, transcripts).
    meet_code = models.CharField(max_length=64, default="", blank=True)
    status = models.CharField(max_length=16, choices=MeetingStatus.choices, default=MeetingStatus.CONFIRMED)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "ical_uid", "recurrence_instance_id"],
                name="unique_meeting_per_team",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "account", "-start_time"], name="idx_meeting_account_time"),
        ]


class MeetingParticipant(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    meeting = models.ForeignKey("customer_analytics.Meeting", on_delete=models.CASCADE, related_name="participants")

    email = models.CharField(max_length=400)
    display_name = models.CharField(max_length=400, default="", blank=True)
    # Resolved person UUID — no FK, person data lives behind the personhog client.
    person_id = models.UUIDField(null=True, blank=True)
    response_status = models.CharField(
        max_length=16, choices=MeetingResponseStatus.choices, default=MeetingResponseStatus.NEEDS_ACTION
    )
    is_organizer = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "meeting", "email"],
                name="unique_participant_per_meeting",
            ),
        ]
