from posthog.models.utils import UUIDModel, CreatedMetaFields, sane_repr
from django.db import models
from posthog.models.team import Team


class ExternalDataSource(CreatedMetaFields, UUIDModel):
    class Type(models.TextChoices):
        STRIPE = "Stripe", "Stripe"

    source_id: models.CharField = models.CharField(max_length=400)
    connection_id: models.CharField = models.CharField(max_length=400)
    destination_id: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    status: models.CharField = models.CharField(max_length=400)
    source_type: models.CharField = models.CharField(max_length=128, choices=Type.choices)
    job_inputs: models.JSONField = models.JSONField(null=True, blank=True)
    are_tables_created: models.BooleanField = models.BooleanField(default=False)

    __repr__ = sane_repr("source_id")

    @property
    def folder_path(self) -> str:
        return f"{self.team_id}/{self.source_type}/{str(self.pk)}"

    @property
    def draft_folder_path(self) -> str:
        return f"team-{self.team_id}/{self.source_type}/{str(self.pk)}-draft"
