from django.db import migrations, models

BATCH_SIZE = 5000


def backfill_query_updated_at(apps, schema_editor):
    SavedQuery = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
    manager = SavedQuery.objects.using(schema_editor.connection.alias)
    # Only `Modified` rows can currently read as edited, so only they need the query timestamp.
    pending = manager.filter(status="Modified", query_updated_at__isnull=True)
    while True:
        ids = list(pending.values_list("pk", flat=True)[:BATCH_SIZE])
        if not ids:
            break
        manager.filter(pk__in=ids).update(query_updated_at=models.F("updated_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0054_datawarehousesavedquery_query_updated_at"),
    ]

    operations = [
        migrations.RunPython(backfill_query_updated_at, migrations.RunPython.noop),
    ]
