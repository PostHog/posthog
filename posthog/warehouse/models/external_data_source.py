import encrypted_fields
from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel, sane_repr


class ExternalDataSource(CreatedMetaFields, UUIDModel):
    class Type(models.TextChoices):
        STRIPE = "Stripe", "Stripe"

    source_id: models.CharField = models.CharField(max_length=400)
    connection_id: models.CharField = models.CharField(max_length=400)
    destination_id: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    status: models.CharField = models.CharField(max_length=400)
    source_type: models.CharField = models.CharField(max_length=128, choices=Type.choices)
    job_inputs: encrypted_fields.fields.EncryptedJSONField = encrypted_fields.fields.EncryptedJSONField(
        null=True, blank=True
    )
    are_tables_created: models.BooleanField = models.BooleanField(default=False)

    __repr__ = sane_repr("source_id")

    @property
    def folder_path(self) -> str:
        return f"team_{self.team_id}_{self.source_type}_{str(self.pk)}".lower().replace("-", "_")

    @property
    def draft_folder_path(self) -> str:
        return f"team_{self.team_id}_{self.source_type}_{str(self.pk)}_draft".lower().replace("-", "_")
