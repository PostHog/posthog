from django.db.models.signals import post_save
from django.dispatch import receiver

from products.data_warehouse.backend.models import DataWarehouseSavedQuery


@receiver(post_save, sender=DataWarehouseSavedQuery)
def sync_saved_query_name_to_node(sender, instance: DataWarehouseSavedQuery, **kwargs):
    """Propagate SavedQuery name changes to related Node."""
    from products.data_modeling.backend.models.node import Node

    # this was originally called on every update to the saved query. it should only happen on
    # saved query name changes.
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "name" not in update_fields:
        return

    # originally i wanted to use save() for this for the validation. but its unnecessary because
    # all it does is sync the name to the query. this also does that without holding the lock for
    # as long.
    Node.objects.filter(saved_query=instance).exclude(name=instance.name).update(name=instance.name)
