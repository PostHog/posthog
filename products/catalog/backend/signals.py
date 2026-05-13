from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete
from django.dispatch import receiver

from products.catalog.backend.models import CatalogNode
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.table import DataWarehouseTable


@receiver(post_delete, sender=DataWarehouseTable)
def cleanup_node_on_warehouse_table_delete(
    sender: type[DataWarehouseTable], instance: DataWarehouseTable, **kwargs: Any
) -> None:
    ct = ContentType.objects.get_for_model(sender)
    CatalogNode.objects.filter(content_type=ct, object_id=instance.id).delete()


@receiver(post_delete, sender=DataWarehouseSavedQuery)
def cleanup_node_on_saved_query_delete(
    sender: type[DataWarehouseSavedQuery], instance: DataWarehouseSavedQuery, **kwargs: Any
) -> None:
    ct = ContentType.objects.get_for_model(sender)
    CatalogNode.objects.filter(content_type=ct, object_id=instance.id).delete()
