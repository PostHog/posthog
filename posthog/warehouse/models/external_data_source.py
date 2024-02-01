import encrypted_fields
from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel, sane_repr
from posthog.warehouse.util import database_sync_to_async
from uuid import UUID


class ExternalDataSource(CreatedMetaFields, UUIDModel):
    class Type(models.TextChoices):
        STRIPE = "Stripe", "Stripe"
        HUBSPOT = "Hubspot", "Hubspot"
        POSTGRES = "Postgres", "Postgres"

    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        PAUSED = "Paused", "Paused"
        ERROR = "Error", "Error"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

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
    prefix: models.CharField = models.CharField(max_length=100, null=True, blank=True)

    __repr__ = sane_repr("id")


@database_sync_to_async
def get_external_data_source(source_id: UUID) -> ExternalDataSource:
    return ExternalDataSource.objects.get(pk=source_id)
