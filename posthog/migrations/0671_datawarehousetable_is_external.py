# Generated by Django 4.2.18 on 2025-02-18 12:06

from django.db import migrations, models


def set_is_external(apps, schema_editor):
    DataWarehouseTable = apps.get_model("posthog", "DataWarehouseTable")
    DataWarehouseTable.objects.filter(created_by_id__isnull=False).update(is_external=True)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0670_querytabstate_querytabstate_unique_team_created_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="datawarehousetable",
            name="is_external",
            field=models.BooleanField(default=False, null=True, blank=True),
        ),
        migrations.RunPython(
            set_is_external,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
