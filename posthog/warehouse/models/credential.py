from posthog.models.utils import UUIDModel, CreatedMetaFields, sane_repr
from django.db import models
from posthog.models.team import Team


class DataWarehouseCredential(CreatedMetaFields, UUIDModel):
    class TableType(models.TextChoices):
        CSV = "csv", "CSV"
        Parquet = "Parquet", "Parquet"

    access_key: models.CharField = models.CharField(max_length=500)
    access_secret: models.CharField = models.CharField(max_length=500)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)

    __repr__ = sane_repr("access_key")
