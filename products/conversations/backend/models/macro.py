from __future__ import annotations

from django.conf import settings
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel
from posthog.utils import generate_short_id


class MacroVisibility(models.TextChoices):
    TEAM = "team", "Team"
    PERSONAL = "personal", "Personal"


class Macro(TeamScopedRootMixin, UUIDModel):
    """A saved reply that agents insert into the composer, optionally applying ticket actions."""

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
    # Reply body: `content` is the markdown/plain-text fallback, `rich_content` the TipTap JSON.
    # Mirrors the dual storage on Ticket messages so the composer can round-trip formatting.
    content = models.TextField(blank=True, default="")
    rich_content = models.JSONField(default=dict, blank=True)
    # Optional ticket actions applied when the macro is used, e.g.
    # {"status": "closed", "priority": "high", "tags": [...], "assignee": {...}}. Empty = text-only.
    actions = models.JSONField(default=dict, blank=True)
    # "team" macros are shared with everyone on the team; "personal" macros are only
    # visible to their creator.
    visibility = models.CharField(max_length=20, choices=MacroVisibility.choices, default=MacroVisibility.TEAM)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_macro"
        unique_together = ("team", "short_id")
        indexes = [
            models.Index(fields=["team_id", "-created_at"], name="conv_macro_team_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} (Team: {self.team})"
