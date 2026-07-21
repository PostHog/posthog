from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

MAX_ENABLED_RULES_PER_TEAM = 20
MIN_RULE_WINDOW_MINUTES = 15
MAX_RULE_WINDOW_MINUTES = 24 * 60
# Below this a "spike" is barely above normal and alerts read as noise.
MIN_SPIKE_MULTIPLIER = 1.5


class TicketAlertRule(TeamScopedRootMixin, UUIDModel):
    # db_constraint=False: a real FK constraint would take SHARE ROW EXCLUSIVE on the
    # hot posthog_team / posthog_user tables on CreateModel. App-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )

    name = models.CharField(max_length=400)
    # Ticket list filters in query-param form — the same key/value strings the tickets list
    # endpoint accepts (status, priority, channel_source, tags, search, ...). Time and ordering
    # params are ignored at evaluation time; the rule's window supplies the time bound.
    filters = models.JSONField(default=dict, blank=True)

    window_minutes = models.PositiveIntegerField(default=120)
    min_count = models.PositiveIntegerField(default=5)
    # When null the rule is absolute-only: fire purely on min_count within the window,
    # with no baseline comparison (the cheapest evaluation path).
    spike_multiplier = models.FloatField(null=True, blank=True)

    enabled = models.BooleanField(default=True)

    last_evaluated_at = models.DateTimeField(null=True, blank=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_ticket_alert_rule"
        indexes = [
            models.Index(fields=["team", "enabled"], name="posthog_con_alert_rule_en_idx"),
        ]

    def __str__(self) -> str:
        return f"TicketAlertRule {self.name} (team {self.team_id})"
