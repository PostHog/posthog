from django.db.models.signals import post_save
from django.dispatch import receiver

from products.data_warehouse.backend.models import DataWarehouseSavedQuery


@receiver(post_save, sender=DataWarehouseSavedQuery)
def sync_saved_query_name_to_node(sender, instance: DataWarehouseSavedQuery, **kwargs):
    """Propagate SavedQuery name changes to related Node."""
    from products.data_modeling.backend.models.node import Node

    # less efficient, but update() doesn't call validation logic and save() does
    # maximally this would return N nodes equal to the number of dags containing the saved_query
    # for the given team. so this shouldn't have too much performance drawback
    for node in Node.objects.filter(saved_query=instance).select_related("saved_query"):
        node.save()
