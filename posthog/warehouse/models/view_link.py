from posthog.models.utils import UUIDModel, CreatedMetaFields, DeletedMetaFields
from django.db import models
from posthog.models.team import Team
from .datawarehouse_saved_query import DataWarehouseSavedQuery


class DataWarehouseViewLink(CreatedMetaFields, UUIDModel, DeletedMetaFields):
    class Type(models.IntegerChoices):
        EVENT = 1, "event"
        PERSON = 2, "person"

    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    table: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(default=Type.EVENT, choices=Type.choices)
    saved_query: models.ForeignKey = models.ForeignKey(DataWarehouseSavedQuery, on_delete=models.CASCADE)
    join_key: models.CharField = models.CharField(max_length=128)
