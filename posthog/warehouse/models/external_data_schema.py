from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel, sane_repr
import uuid


class ExternalDataSchema(CreatedMetaFields, UUIDModel):
    name: models.CharField = models.CharField(max_length=400)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    source: models.ForeignKey = models.ForeignKey(
        "posthog.ExternalDataSource", related_name="schemas", on_delete=models.CASCADE
    )
    table: models.ForeignKey = models.ForeignKey(
        "posthog.DataWarehouseTable", on_delete=models.CASCADE, null=True, blank=True
    )
    should_sync: models.BooleanField = models.BooleanField(default=True)
    latest_error: models.TextField = models.TextField(
        null=True, help_text="The latest error that occurred when syncing this schema."
    )

    __repr__ = sane_repr("name")


def get_active_schemas_for_source_id(source_id: uuid.UUID, team_id: int):
    schemas = ExternalDataSchema.objects.filter(team_id=team_id, source_id=source_id, should_sync=True).values().all()
    return [val["name"] for val in schemas]


def get_all_schemas_for_source_id(source_id: uuid.UUID, team_id: int):
    schemas = ExternalDataSchema.objects.filter(team_id=team_id, source_id=source_id).values().all()
    return [val["name"] for val in schemas]


def sync_old_schemas_with_new_schemas(new_schemas: list, source_id: uuid.UUID, team_id: int):
    old_schemas = get_all_schemas_for_source_id(source_id=source_id, team_id=team_id)
    schemas_to_create = [schema for schema in new_schemas if schema not in old_schemas]

    for schema in schemas_to_create:
        ExternalDataSchema.objects.create(name=schema, team_id=team_id, source_id=source_id)
