from django.db import migrations

from products.data_warehouse.backend.models import DataWarehouseSavedQuery

CHUNK_SIZE = 1000


def forwards_func(apps, schema_editor):
    SavedQuery = apps.get_model("data_warehouse", "DataWarehouseSavedQuery")

    chunk = []
    for query in (
        SavedQuery.objects.filter(managed_viewset__isnull=False).only("id", "origin").iterator(chunk_size=CHUNK_SIZE)
    ):
        query.origin = DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET
        chunk.append(query)

        if len(chunk) == CHUNK_SIZE:
            SavedQuery.objects.bulk_update(chunk, ["origin"])
            chunk = []

    if chunk:
        SavedQuery.objects.bulk_update(chunk, ["origin"])

    chunk = []
    for query in (
        SavedQuery.objects.filter(managed_viewset__isnull=True).only("id", "origin").iterator(chunk_size=CHUNK_SIZE)
    ):
        query.origin = DataWarehouseSavedQuery.Origin.DATA_WAREHOUSE
        chunk.append(query)

        if len(chunk) == CHUNK_SIZE:
            SavedQuery.objects.bulk_update(chunk, ["origin"])
            chunk = []

    if chunk:
        SavedQuery.objects.bulk_update(chunk, ["origin"])


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0007_alter_saved_query_origin_choices"),
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_func),
    ]
