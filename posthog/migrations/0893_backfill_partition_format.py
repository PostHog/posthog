# generated manually to backfill partition formats to "month" for existing syncs
# in the data warehouse product

from django.db import migrations
from django.db.models import Q

from posthog.warehouse.models import ExternalDataSchema as ExternalDataSchemaModel


def forwards(apps, _):
    ExternalDataSchema: ExternalDataSchemaModel = apps.get_model("posthog", "ExternalDataSchema")
    # temporal io backfill partition format to day
    affected_temporalio_schemata = ExternalDataSchema.objects.filter(
        Q(source__source_type="TemporalIO")
        & Q(deleted=False)
        & Q(sync_type_config__partitioning_enabled=True)
        & Q(sync_type_config__partition_mode="datetime")
        & Q(sync_type_config__partition_format__isnull=True)
    )
    for schema in affected_temporalio_schemata:
        schema.sync_type_config["partition_format"] = "day"
        schema.sync_type_config["backfilled_partition_format"] = True
        schema.save()

    # google ads backfill partition format to day
    affected_google_ads_schemata = ExternalDataSchema.objects.filter(
        Q(source__source_type="GoogleAds")
        & Q(deleted=False)
        & Q(sync_type_config__partitioning_enabled=True)
        & Q(sync_type_config__partition_mode="datetime")
        & Q(sync_type_config__partition_format__isnull=True)
    )
    for schema in affected_google_ads_schemata:
        schema.sync_type_config["partition_format"] = "day"
        schema.sync_type_config["backfilled_partition_format"] = True
        schema.save()

    # backfill partition format to month for remaining tables
    affected_schemata = ExternalDataSchema.objects.filter(
        ~Q(source__source_type__in=["GoogleAds", "TemporalIO"])
        & Q(deleted=False)
        & Q(sync_type_config__partitioning_enabled=True)
        & Q(sync_type_config__partition_mode="datetime")
        & Q(sync_type_config__partition_format__isnull=True)
    )
    for schema in affected_schemata:
        schema.sync_type_config["partition_format"] = "month"
        schema.sync_type_config["backfilled_partition_format"] = True
        schema.save()


def backwards(apps, _):
    ExternalDataSchema: ExternalDataSchemaModel = apps.get_model("posthog", "ExternalDataSchema")
    affected_schemata = ExternalDataSchema.objects.filter(Q(sync_type_config__backfilled=True))
    for schema in affected_schemata:
        schema.sync_type_config.pop("partition_format", None)
        schema.sync_type_config.pop("backfilled_partition_format", None)
        schema.save()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0892_alter_integration_kind"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
