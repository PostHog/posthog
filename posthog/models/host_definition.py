from django.db import models
from django.utils import timezone

from posthog.models.utils import UniqueConstraintByExpression, UUIDTModel


# NOTE: This model is deprecated. It was created as an attempt to track all of the domains that are using PostHog.
# This wasn't very performant inside propdefs, and for that reason it was sunsetted.
#
# # TODO: Enable `@deprecated` once we move to Python 3.13
# @deprecated("This model is no longer used due to performance issues with propdefs")
class HostDefinition(UUIDTModel):
    team = models.ForeignKey(
        "Team",
        on_delete=models.CASCADE,
        related_name="host_definitions",
        related_query_name="host_definition",
    )
    project = models.ForeignKey(
        "Project",
        null=True,
        on_delete=models.CASCADE,
        related_name="host_definitions",
        related_query_name="host_definition",
    )
    host = models.CharField(max_length=400)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "posthog_hostdefinition"
        indexes = [
            models.Index(fields=["project", "host"], name="hostdefinition_project_idx"),
            models.Index(fields=["team", "host"], name="hostdefinition_team_idx"),
        ]
        unique_together = ("team", "host")
        constraints = [
            UniqueConstraintByExpression(
                name="hostdefinition_coalesced_idx",
                expression="(coalesce(project_id, team_id), host)",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.host} / {self.team.name}"
