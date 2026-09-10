from __future__ import annotations

from django.conf import settings
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.conversations.backend.models.constants import Priority


class TicketPatternStatus(models.TextChoices):
    OPEN = "open", "Open"
    CONFIRMED = "confirmed", "Confirmed"
    DISMISSED = "dismissed", "Dismissed"
    RESOLVED = "resolved", "Resolved"


class TicketPatternSource(models.TextChoices):
    TERMS = "terms", "Term match"
    EMBEDDINGS = "embeddings", "Embeddings"


class TicketPattern(TeamScopedRootMixin, UUIDModel):
    """A cluster of tickets from several distinct requesters about one topic inside a short window.

    One open row per (team, fingerprint): a still-firing topic updates its open pattern instead of
    minting a new one, and the partial unique constraint below is the backstop against a racing tick.
    """

    # db_index=False: both indexes below lead with team, so the implicit one only costs writes.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    # Stable key for the topic, e.g. "terms:login password". Dedupe keys on it, not on the title.
    # Wider than `topic` because it carries the source prefix on top of a full-length topic.
    fingerprint = models.CharField(max_length=255)
    topic = models.CharField(max_length=200)
    source = models.CharField(max_length=16, choices=TicketPatternSource.choices, default=TicketPatternSource.TERMS)
    title = models.CharField(max_length=300)
    summary = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=TicketPatternStatus.choices, default=TicketPatternStatus.OPEN)
    severity = models.CharField(max_length=16, choices=Priority.choices, default=Priority.MEDIUM)

    ticket_count = models.PositiveIntegerField(default=0)
    requester_count = models.PositiveIntegerField(default=0)
    peak_ticket_count = models.PositiveIntegerField(default=0)
    first_ticket_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    evidence = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_ticket_pattern"
        indexes = [
            models.Index(fields=["team", "status", "-last_seen_at"], name="conv_pattern_team_status_idx"),
            models.Index(fields=["team", "-opened_at"], name="conv_pattern_team_opened_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "fingerprint"],
                condition=models.Q(status="open"),
                name="conv_pattern_one_open_per_fp",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.status}, team {self.team_id})"


class TicketPatternEvidence(TeamScopedRootMixin, UUIDModel):
    """A ticket that contributed to a pattern. Capped per pattern by the writer: a pattern points at
    tickets, it does not materialize a report."""

    # db_index=False: the (team, ticket) index below leads with team.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    # db_index=False: the unique (pattern, ticket) below leads with pattern, which serves both
    # the reverse lookup and the cascade.
    pattern = models.ForeignKey(
        TicketPattern, on_delete=models.CASCADE, db_index=False, related_name="evidence_tickets"
    )
    ticket = models.ForeignKey("conversations.Ticket", on_delete=models.CASCADE, related_name="+")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_conversations_ticket_pattern_evidence"
        constraints = [
            models.UniqueConstraint(fields=["pattern", "ticket"], name="conv_pattern_evid_unique"),
        ]
        indexes = [
            models.Index(fields=["team", "ticket"], name="conv_pattern_evid_ticket_idx"),
        ]


class TicketTopicBaseline(TeamScopedRootMixin, UUIDModel):
    """What a topic's arrival rate normally looks like for this team, learned from its own history.

    Derived, never authored. Confirm and dismiss counts feed back into the bar the detector sets for
    the topic, so a false positive gets quieter and a confirmed topic gets easier to reopen.
    """

    # db_index=False: the unique (team, topic) below leads with team.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    topic = models.CharField(max_length=200)
    mean_per_hour = models.FloatField(default=0.0)
    spread = models.FloatField(default=0.0)
    distinct_days_seen = models.PositiveIntegerField(default=0)
    dismiss_count = models.PositiveIntegerField(default=0)
    confirm_count = models.PositiveIntegerField(default=0)
    sample_window_days = models.PositiveIntegerField(default=30)
    refreshed_at = models.DateTimeField()

    class Meta:
        db_table = "posthog_conversations_ticket_topic_baseline"
        constraints = [
            models.UniqueConstraint(fields=["team", "topic"], name="conv_topic_baseline_unique"),
        ]
