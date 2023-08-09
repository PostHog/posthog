from posthog.models.utils import UUIDModel, CreatedMetaFields, DeletedMetaFields
from django.db import models
from posthog.models.team import Team
from .datawarehouse_saved_query import DataWarehouseSavedQuery


class DataWarehouseViewLink(CreatedMetaFields, UUIDModel, DeletedMetaFields):

    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    table: models.CharField = models.CharField(max_length=400)
    from_join_key: models.CharField = models.CharField(max_length=400)
    saved_query: models.ForeignKey = models.ForeignKey(DataWarehouseSavedQuery, on_delete=models.CASCADE)
    to_join_key: models.CharField = models.CharField(max_length=400)
