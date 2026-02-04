from django.db import migrations
from django.db.models import Q
from django.db.models.functions import Now


def fix_orphaned_tables(apps, schema_editor):
    DataWarehouseTable = apps.get_model("data_warehouse", "DataWarehouseTable")
    DataWarehouseJoin = apps.get_model("data_warehouse", "DataWarehouseJoin")

    orphaned_tables = DataWarehouseTable.objects.filter(
        external_data_source__deleted=True,
    ).exclude(deleted=True)

    orphaned_table_names = list(orphaned_tables.values_list("name", "team_id"))

    # Mirrors join cleanup from DataWarehouseTable.soft_delete()
    for name, team_id in orphaned_table_names:
        DataWarehouseJoin.objects.filter(
            Q(team_id=team_id) & (Q(source_table_name=name) | Q(joining_table_name=name)),
        ).exclude(deleted=True).update(deleted=True, deleted_at=Now())

    orphaned_tables.update(deleted=True, deleted_at=Now())


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0018_fix_orphaned_schemas"),
    ]

    operations = [
        migrations.RunPython(fix_orphaned_tables, migrations.RunPython.noop),
    ]
