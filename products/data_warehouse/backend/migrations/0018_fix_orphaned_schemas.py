from django.db import migrations
from django.db.models.functions import Now


def fix_orphaned_schemas(apps, schema_editor):
    ExternalDataSchema = apps.get_model("data_warehouse", "ExternalDataSchema")
    ExternalDataSchema.objects.filter(
        source__deleted=True,
        deleted=False,
    ).update(deleted=True, deleted_at=Now())


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0017_alter_externaldatasource_source_type"),
    ]

    operations = [
        migrations.RunPython(fix_orphaned_schemas, migrations.RunPython.noop),
    ]
