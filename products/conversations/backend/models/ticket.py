from typing import TYPE_CHECKING

from django.db import models, transaction
from django.utils import timezone

from posthog.models.utils import UUIDTModel

from .constants import Channel, ChannelDetail, Priority, Status

if TYPE_CHECKING:
    from posthog.models import Person


def _extend_update_fields(save_kwargs: dict, field: str) -> None:
    """Include a field set by save() in an update_fields-limited save."""
    update_fields = save_kwargs.get("update_fields")
    if update_fields is not None:
        save_kwargs["update_fields"] = [*update_fields, field]


class TicketManager(models.Manager):
    def create_with_number(self, **kwargs):
        """
        Create a ticket with an auto-incrementing ticket_number.
        Uses SELECT FOR UPDATE on Team row to serialize ticket creation per team.
        """
        from posthog.models import Team

        team = kwargs.get("team")
        if not team:
            raise ValueError("team is required")

        with transaction.atomic():
            # Lock team row to serialize ticket creation for this team
            Team.objects.select_for_update().get(id=team.id)

            max_num = self.filter(team=team).aggregate(models.Max("ticket_number"))["ticket_number__max"] or 0
            kwargs["ticket_number"] = max_num + 1
            return self.create(**kwargs)


class Ticket(UUIDTModel):
    objects = TicketManager()

    # Dynamic attribute set by TicketViewSet._attach_persons_to_tickets for serialization
    person: "Person | None"

    # Snapshot of status as last loaded / saved, used by save() to tell a real transition
    # into or out of `resolved` from a save that just happens to touch a resolved ticket.
    # Set in __init__/from_db/refresh_from_db; not a model field.
    _status_at_load: str | None

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    ticket_number = models.PositiveIntegerField()
    channel_source = models.CharField(max_length=20, choices=Channel, default=Channel.WIDGET)
    channel_detail = models.CharField(max_length=30, choices=ChannelDetail, null=True, blank=True)
    widget_session_id = models.CharField(max_length=64, db_index=True)  # Random UUID for access control
    distinct_id = models.CharField(max_length=400)  # PostHog distinct_id for Person linking only
    status = models.CharField(max_length=20, choices=Status, default=Status.NEW)
    priority = models.CharField(max_length=20, choices=Priority, null=True, blank=True)
    anonymous_traits = models.JSONField(default=dict, blank=True)
    # Trust signal (tri-state):
    #   True  — the claimed identity was attested by the server (widget HMAC,
    #           SPF-authenticated email, or a signature-validated platform webhook).
    #   False — assessed but not attested (anonymous claim we couldn't verify).
    #   None  — unknown; we never assessed it (e.g. predates this signal and the
    #           channel doesn't structurally guarantee verification).
    identity_verified = models.BooleanField(null=True)
    ai_resolved = models.BooleanField(default=False)
    escalation_reason = models.TextField(null=True, blank=True)
    ai_triage = models.JSONField(default=dict, blank=True)

    # Unread message counters
    unread_customer_count = models.IntegerField(default=0)  # Messages customer hasn't seen (from team/AI)
    unread_team_count = models.IntegerField(default=0)  # Messages team hasn't seen (from customer)

    # Denormalized message stats (updated via signal on Comment save)
    message_count = models.IntegerField(default=0)
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_message_text = models.CharField(max_length=500, null=True, blank=True)  # Truncated preview

    # Slack channel fields (only set for channel_source="slack")
    slack_channel_id = models.CharField(max_length=64, null=True, blank=True)  # Slack channel ID
    slack_thread_ts = models.CharField(max_length=64, null=True, blank=True)  # Slack thread timestamp (thread ID)
    slack_team_id = models.CharField(max_length=64, null=True, blank=True)  # Slack workspace/team ID

    # Teams channel fields (only set for channel_source="teams")
    teams_channel_id = models.CharField(max_length=128, null=True, blank=True)
    teams_conversation_id = models.CharField(max_length=256, null=True, blank=True)  # Reply chain / thread ID
    teams_service_url = models.URLField(max_length=512, null=True, blank=True)  # Bot Connector endpoint for replies
    teams_tenant_id = models.CharField(max_length=64, null=True, blank=True)
    # Shared-channel thread reply poller watermark (Graph createdDateTime of last ingested reply).
    teams_thread_replies_synced_at = models.DateTimeField(null=True, blank=True)

    # GitHub channel fields (only set for channel_source="github")
    github_repo = models.CharField(max_length=256, null=True, blank=True)  # owner/repo
    github_issue_number = models.PositiveIntegerField(null=True, blank=True)

    # Email channel fields (only set for channel_source="email")
    email_config = models.ForeignKey(
        "conversations.EmailChannel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    email_subject = models.CharField(max_length=500, null=True, blank=True)
    email_from = models.EmailField(null=True, blank=True)
    cc_participants = models.JSONField(default=list, blank=True)

    # Session context (captured when ticket is created)
    session_id = models.CharField(max_length=64, null=True, blank=True)  # PostHog session ID
    session_context = models.JSONField(default=dict, blank=True)  # session_replay_url, current_url, etc.

    # SLA deadline — set via workflows, null means no SLA
    sla_due_at = models.DateTimeField(null=True, blank=True)

    # Lifecycle timestamps, denormalized for support metrics (TTFR, resolution time).
    # first_response_at: first customer-visible team/AI reply that isn't the message which opened
    #   the ticket, stamped once by the message signal.
    # last_resolved_at: when the ticket most recently entered `resolved`, stamped by save(). Kept
    #   through a reopen and overwritten by the next resolve, so it stays queryable as history and
    #   `status` — not this column — is what says whether a ticket is resolved right now.
    first_response_at = models.DateTimeField(null=True, blank=True)
    last_resolved_at = models.DateTimeField(null=True, blank=True)

    # Snooze — when set, ticket is "on hold" until this time, then auto-reopened by wake task
    snoozed_until = models.DateTimeField(null=True, blank=True)

    # Customer's PostHog org group key, resolved once at creation or on a later message
    # (local org pk, cross-region analytics key, or the person's organization_id property).
    organization_id = models.CharField(max_length=400, null=True, blank=True)
    # How organization_id was resolved: "person" (the requester's identity) or
    # "slack_channel_account" (inferred from the customer analytics account linked to the Slack channel).
    organization_id_source = models.CharField(max_length=32, null=True, blank=True)

    # Zendesk import dedup — set when a ticket is imported from Zendesk Support.
    # No standalone index: the partial unique constraint below covers the dedup lookup
    # (team + zendesk_ticket_id), mirroring the GitHub issue-number pattern.
    zendesk_ticket_id = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_ticket"
        indexes = [
            models.Index(fields=["team", "widget_session_id"]),  # Access control queries
            models.Index(fields=["team", "distinct_id"]),  # Person linking queries
            models.Index(fields=["team", "status"]),
            models.Index(fields=["team", "-ticket_number"], name="posthog_con_team_id_ticket_idx"),  # MAX() lookups
            models.Index(fields=["team", "session_id"]),  # Session context queries
            # Slack thread lookup: find ticket by (team, slack_channel_id, slack_thread_ts)
            models.Index(
                fields=["team", "slack_channel_id", "slack_thread_ts"],
                name="posthog_con_slack_thread_idx",
            ),
            # Teams thread lookup: find ticket by (team, teams_channel_id, teams_conversation_id)
            models.Index(
                fields=["team", "teams_channel_id", "teams_conversation_id"],
                name="posthog_con_teams_thread_idx",
            ),
            # Dashboard ordering optimization
            models.Index(fields=["team", "-updated_at"], name="posthog_con_team_updated_idx"),
            # Dashboard filtered + ordered queries
            models.Index(fields=["team", "status", "-updated_at"], name="posthog_con_status_upd_idx"),
            # SLA sort + filter. The dashboard sorts by "sla_due_at <dir> NULLS LAST, ticket_number
            # DESC"; one expression index per direction makes each page a top-N index scan instead
            # of a full sort of the mostly-NULL table (a plain ascending index can't serve DESC
            # NULLS LAST, and lacks the ticket_number tiebreaker). The leading (team_id, sla_due_at)
            # prefix also serves the SLA state filter, so these supersede a plain (team, sla_due_at).
            models.Index(
                models.F("team_id"),
                models.F("sla_due_at").asc(nulls_last=True),
                models.F("ticket_number").desc(),
                name="posthog_con_sla_asc_idx",
            ),
            models.Index(
                models.F("team_id"),
                models.F("sla_due_at").desc(nulls_last=True),
                models.F("ticket_number").desc(),
                name="posthog_con_sla_desc_idx",
            ),
            # Snooze sort + filter: same asc/desc expression-index pair. The leading prefix serves
            # the snoozed isnull filter, so these supersede a plain (team, snoozed_until) index.
            models.Index(
                models.F("team_id"),
                models.F("snoozed_until").asc(nulls_last=True),
                models.F("ticket_number").desc(),
                name="posthog_con_snooze_asc_idx",
            ),
            models.Index(
                models.F("team_id"),
                models.F("snoozed_until").desc(nulls_last=True),
                models.F("ticket_number").desc(),
                name="posthog_con_snooze_desc_idx",
            ),
            # Snooze: wake task (cross-team, only non-null rows)
            models.Index(
                fields=["snoozed_until"],
                name="posthog_con_snooze_wake_idx",
                condition=models.Q(snoozed_until__isnull=False),
            ),
            models.Index(fields=["organization_id"], name="posthog_org_id_idx"),
            models.Index(
                fields=["organization_id", "slack_channel_id"],
                name="posthog_org_slack_ch_idx",
                condition=models.Q(channel_source="slack"),
            ),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team", "ticket_number"], name="unique_ticket_number_per_team"),
            models.UniqueConstraint(
                fields=["team", "github_repo", "github_issue_number"],
                condition=models.Q(github_repo__isnull=False, github_issue_number__isnull=False),
                name="posthog_con_github_issue_uniq",
            ),
            models.UniqueConstraint(
                fields=["team", "zendesk_ticket_id"],
                condition=models.Q(zendesk_ticket_id__isnull=False),
                name="posthog_con_zendesk_ticket_uniq",
            ),
        ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._status_at_load = None

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        # A deferred load leaves the snapshot unset rather than triggering a refetch of status;
        # save() then leaves last_resolved_at alone instead of guessing at a transition.
        if "status" in field_names:
            instance._status_at_load = instance.status
        return instance

    def refresh_from_db(self, *args, **kwargs) -> None:
        # Refreshing replaces in-memory state with DB state, so the transition baseline has to
        # follow, or the next save() would compare against a stale status.
        super().refresh_from_db(*args, **kwargs)
        self._status_at_load = self.status

    def save(self, *args, **kwargs) -> None:
        self._stamp_last_resolved_at(kwargs)
        super().save(*args, **kwargs)
        self._status_at_load = self.status

    def _stamp_last_resolved_at(self, save_kwargs: dict) -> None:
        """Stamp last_resolved_at when this save moves the ticket into `resolved`.

        Status is written from many places (agent UI, external/workflow API, GitHub issue sync,
        snooze wake task) and all of them go through save(), so this is the one spot that can't
        be forgotten. The stamp is never cleared: a reopen leaves the previous resolve time in
        place so "resolved during this period" stays answerable, and the next resolve overwrites
        it.
        """
        update_fields = save_kwargs.get("update_fields")
        if update_fields is not None and "status" not in update_fields:
            # This save isn't writing status, so it can't be a transition into resolved.
            return

        if self.status != Status.RESOLVED:
            return

        # Only on entry, so a later save that re-asserts `resolved` keeps the original time.
        # Rows that reached `resolved` without save() (the Zendesk import writes them with
        # bulk_create) stay NULL rather than being back-dated to whenever a later save happened
        # to touch them. UUIDTModel assigns pk in __init__, so _state.adding is the only new-row
        # signal.
        if self._state.adding or self._status_at_load != Status.RESOLVED:
            self.last_resolved_at = timezone.now()
            _extend_update_fields(save_kwargs, "last_resolved_at")

    def __str__(self):
        return f"Ticket {self.id} - {self.widget_session_id[:8]}..."
