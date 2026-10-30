from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class TicketMacro(ModelActivityMixin, TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """A shared reply an agent can insert into the ticket composer."""

    activity_logging_on_delete = True

    # db_constraint=False: a real FK constraint takes SHARE ROW EXCLUSIVE on the parent while
    # migrating, stalling writes under traffic.
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )

    name = models.CharField(max_length=200)
    shortcut = models.CharField(max_length=50, null=True, blank=True)
    body = models.TextField()
    usage_count = models.PositiveIntegerField(default=0, db_default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_ticket_macro"
        constraints = [
            # Null shortcuts are not unique: several macros can have no slash command.
            models.UniqueConstraint(
                fields=["team", "shortcut"],
                condition=models.Q(shortcut__isnull=False),
                name="conv_macro_team_shortcut_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "-usage_count"], name="conv_macro_team_usage_idx"),
        ]

    def __str__(self) -> str:
        return self.name
