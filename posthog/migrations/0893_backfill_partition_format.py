# generated manually to backfill partition formats to "month" for existing syncs
# in the data warehouse product

from django.db import migrations
from django.db.models import Q

from posthog.warehouse.models import ExternalDataSchema as ExternalDataSchemaModel


def forwards(apps, _):
    ExternalDataSchema: ExternalDataSchemaModel = apps.get_model("posthog", "ExternalDataSchema")
    affected_schemata = ExternalDataSchema.objects.filter(
        Q(
            deleted=False,
            sync_type_config__partitioning_enabled=True,
            sync_type_config__partition_mode="datetime",
            sync_type_config__partition_format__isnull=True,
        )
    )
    for schema in affected_schemata:
        schema.sync_type_config["partition_format"] = "month"
        schema.sync_type_config["backfilled_partition_format"] = True
        schema.save()


def backwards(apps, _):
    ExternalDataSchema: ExternalDataSchemaModel = apps.get_model("posthog", "ExternalDataSchema")
    affected_schemata = ExternalDataSchema.objects.filter(Q(sync_type_config__backfilled=True))
    for schema in affected_schemata:
        schema.sync_type_config["partition_format"] = None
        schema.sync_type_config.pop("backfilled_partition_format", None)
        schema.save()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0892_alter_integration_kind"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
