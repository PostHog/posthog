from datetime import datetime
from typing import cast
from warnings import warn

from django.db import models

from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDTModel


class DataWarehouseViewLink(CreatedMetaFields, UUIDTModel, DeletedMetaFields):
    class Meta:
        db_table = "posthog_datawarehouseviewlink"

    """Deprecated model, use DataWarehouseJoin instead"""

    def __init_subclass__(cls, **kwargs):
        """This throws a deprecation warning on subclassing."""
        warn("DataWarehouseViewLink is deprecated, use DataWarehouseJoin", DeprecationWarning, stacklevel=2)
        super().__init_subclass__(**kwargs)

    def __init__(self, *args, **kwargs):
        """This throws a deprecation warning on initialization."""
        warn("DataWarehouseViewLink is deprecated, use DataWarehouseJoin", DeprecationWarning, stacklevel=2)
        super().__init__(*args, **kwargs)

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    table = models.CharField(max_length=128)
    from_join_key = models.CharField(max_length=400)
    saved_query = models.ForeignKey("data_modeling.DataWarehouseSavedQuery", on_delete=models.CASCADE)
    to_join_key = models.CharField(max_length=400)


class DataWarehouseJoin(CreatedMetaFields, UUIDTModel, DeletedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    source_table_name = models.CharField(max_length=400)
    source_table_key = models.CharField(max_length=400)
    joining_table_name = models.CharField(max_length=400)
    joining_table_key = models.CharField(max_length=400)
    field_name = models.CharField(max_length=400)
    configuration = models.JSONField(default=dict, null=True)

    class Meta:
        db_table = "posthog_datawarehousejoin"

    @property
    def joining_table_name_chain(self) -> list[str | int]:
        return cast(list[str | int], self.joining_table_name.split("."))

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = datetime.now()
        self.save()

    @classmethod
    def create_if_missing(cls, **attrs: object) -> None:
        """Create a join with these attributes unless a matching one already exists.

        Tolerates pre-existing duplicates: several paths create the same join and there's no
        unique constraint, so more than one un-deleted match can exist. A plain get_or_create
        would then raise MultipleObjectsReturned and surface as a 500 during source setup.
        """
        if not cls.objects.filter(**attrs).exists():
            cls.objects.create(**attrs)
