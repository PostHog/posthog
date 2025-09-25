from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDTModel


class DataWarehouseSnapshotConfig(CreatedMetaFields, UUIDTModel, DeletedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    saved_query = models.OneToOneField("posthog.DataWarehouseSavedQuery", on_delete=models.CASCADE)
    config = models.JSONField(default=dict)
