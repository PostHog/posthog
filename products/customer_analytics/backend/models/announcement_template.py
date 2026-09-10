from __future__ import annotations

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class AnnouncementTemplate(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """A reusable, team-shared announcement message body.

    A template holds only the message text — never recipients. A CS person inserts a
    template into the announcement composer, then chooses the Slack channels fresh at
    send time (see ``Announcement``). Templates are soft-deleted so a template can leave
    the picker without a name collision blocking reuse of that name later.
    """

    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )

    name = models.CharField(max_length=255)
    message = models.TextField()
    deleted = models.BooleanField(default=False)

    class Meta(TeamScopedRootMixin.Meta):
        default_manager_name = "all_teams"
        constraints = [
            # One live template per name per team; a soft-deleted row frees the name again.
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=models.Q(deleted=False),
                name="ca_ann_template_uniq_name",
            ),
        ]
        indexes = [
            models.Index(fields=["team_id", "name"], name="ca_ann_template_team_idx"),
        ]

    def __str__(self) -> str:
        return self.name
