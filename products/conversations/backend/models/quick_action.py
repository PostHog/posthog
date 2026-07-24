from __future__ import annotations

from django.conf import settings
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel
from posthog.utils import generate_short_id


class QuickActionVisibility(models.TextChoices):
    TEAM = "team", "Team"
    PERSONAL = "personal", "Personal"


class QuickAction(TeamScopedRootMixin, UUIDModel):
    """A saved action an agent triggers from the composer. When used it inserts its reply (if any),
    applies its ticket actions (if any), and runs its workflow (if any) — in any combination."""

    # db_constraint=False on the hot-table FKs (team, user) so CreateModel takes no lock
    # on posthog_team / posthog_user; app-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )

    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=400, blank=True, default="")

    # --- Reply (optional) ---
    # `content` is the markdown/plain-text fallback, `rich_content` the TipTap JSON. Mirrors the
    # dual storage on Ticket messages so the composer can round-trip formatting.
    content = models.TextField(blank=True, default="")
    rich_content = models.JSONField(default=dict, blank=True)
    # Optional ticket actions applied when used, e.g.
    # {"status": "closed", "priority": "high", "tags": [...], "assignee": {...}}.
    actions = models.JSONField(default=dict, blank=True)

    # --- Workflow (optional) ---
    # Soft reference to a HogFlow (products/workflows) id — no cross-product FK; the API layer
    # validates that it resolves to an active workflow for the team. When set, using the quick
    # action runs the workflow against the ticket in addition to inserting the reply above.
    workflow_id = models.UUIDField(null=True, blank=True)

    # "team" quick actions are shared with everyone on the team; "personal" ones are only
    # visible to their creator.
    visibility = models.CharField(
        max_length=20, choices=QuickActionVisibility.choices, default=QuickActionVisibility.TEAM
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_quick_action"
        unique_together = ("team", "short_id")
        indexes = [
            models.Index(fields=["team_id", "-created_at"], name="conv_quick_action_team_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} (Team: {self.team})"
