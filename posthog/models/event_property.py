from django.db import models
from django.db.models.expressions import F
from django.db.models.functions import Coalesce

from posthog.models.team import Team
from posthog.models.utils import UniqueConstraintByExpression, sane_repr


class EventProperty(models.Model):
    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True)
    event = models.CharField(max_length=400, null=False)
    property = models.CharField(max_length=400, null=False)

    class Meta:
        constraints = [
            UniqueConstraintByExpression(
                concurrently=True,
                name="posthog_event_property_unique_proj_event_property",
                expression="(coalesce(project_id, team_id), event, property)",
            ),
        ]
        indexes = [
            # Index on project_id foreign key
            models.Index(fields=["project"], name="posthog_eve_proj_id_dd2337d2"),
            models.Index(fields=["team", "event"]),
            models.Index(Coalesce(F("project_id"), F("team_id")), F("event"), name="posthog_eve_proj_id_22de03_idx"),
            models.Index(fields=["team", "property"]),
            models.Index(Coalesce(F("project_id"), F("team_id")), F("property"), name="posthog_eve_proj_id_26dbfb_idx"),
        ]

    __repr__ = sane_repr("event", "property", "team_id")
