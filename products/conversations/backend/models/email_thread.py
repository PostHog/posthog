from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

EMAIL_THREAD_COMMENT_SCOPE = "EmailThread"


class EmailThreadAccountMatchSource(models.TextChoices):
    KNOWN_EMAIL = "known_email", "Known email"
    PERSON_GROUP = "person_group", "Person group"
    EMAIL_DOMAIN = "email_domain", "Email domain"


class EmailThreadMessageDirection(models.TextChoices):
    INBOUND = "inbound", "Inbound"
    OUTBOUND = "outbound", "Outbound"


class EmailThreadParticipantKind(models.TextChoices):
    INTERNAL = "internal", "Internal"
    CUSTOMER = "customer", "Customer"


class EmailThread(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    canonical_thread_key = models.CharField(max_length=998)
    subject = models.TextField(default="", blank=True)
    first_message_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    message_count = models.PositiveIntegerField(default=0)
    preview = models.CharField(max_length=500, default="", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_email_thread"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "canonical_thread_key"],
                name="unique_email_thread_key_per_team",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "-last_message_at"], name="email_thread_team_last_idx"),
        ]


class EmailThreadAccountLink(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    thread = models.ForeignKey("conversations.EmailThread", on_delete=models.CASCADE, related_name="account_links")
    account_id = models.CharField(max_length=64)
    account_external_id = models.CharField(max_length=400, null=True, blank=True)
    match_source = models.CharField(max_length=32, choices=EmailThreadAccountMatchSource.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_email_thread_account_link"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "thread", "account_id"],
                name="unique_email_thread_account_link",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "account_id", "thread"], name="email_link_team_account_idx"),
        ]


class EmailThreadMessage(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    thread = models.ForeignKey("conversations.EmailThread", on_delete=models.CASCADE, related_name="messages")
    comment = models.OneToOneField(
        "posthog.Comment",
        on_delete=models.RESTRICT,
        db_constraint=False,
        related_name="email_thread_message",
    )
    message_id = models.CharField(max_length=998, null=True, blank=True)
    in_reply_to = models.CharField(max_length=998, null=True, blank=True)
    references = models.JSONField(default=list, blank=True)
    sent_at = models.DateTimeField()
    sender_email = models.CharField(max_length=400)
    sender_name = models.CharField(max_length=400, default="", blank=True)
    to_recipients = models.JSONField(default=list, blank=True)
    cc_recipients = models.JSONField(default=list, blank=True)
    sender_authenticated = models.BooleanField(default=False, db_default=False)
    direction = models.CharField(max_length=16, choices=EmailThreadMessageDirection.choices)
    source_type = models.CharField(max_length=64)
    source_id = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_conversations_email_thread_message"
        ordering = ["sent_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_type", "source_id"],
                name="unique_email_message_source_per_team",
            ),
            models.UniqueConstraint(
                fields=["team", "message_id"],
                condition=models.Q(message_id__isnull=False) & ~models.Q(message_id=""),
                name="unique_email_message_id_per_team",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "thread", "sent_at", "id"], name="email_message_thread_time_idx"),
        ]


class EmailThreadParticipant(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    thread = models.ForeignKey("conversations.EmailThread", on_delete=models.CASCADE, related_name="participants")
    email = models.CharField(max_length=400)
    display_name = models.CharField(max_length=400, default="", blank=True)
    kind = models.CharField(max_length=16, choices=EmailThreadParticipantKind.choices)
    person_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_email_thread_participant"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "thread", "email"],
                name="unique_email_thread_participant",
            ),
        ]
