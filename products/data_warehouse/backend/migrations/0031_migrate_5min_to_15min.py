from datetime import timedelta

from django.db import migrations


def migrate_5min_to_15min(apps, schema_editor):
    DataWarehouseSavedQuery = apps.get_model("data_warehouse", "DataWarehouseSavedQuery")
    DataWarehouseSavedQuery.objects.filter(sync_frequency_interval=timedelta(minutes=5)).update(
        sync_frequency_interval=timedelta(minutes=15)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0030_externaldataschema_description"),
    ]

    operations = [
        migrations.RunPython(migrate_5min_to_15min, migrations.RunPython.noop),
    ]
