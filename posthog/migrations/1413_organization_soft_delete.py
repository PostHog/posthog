from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1412_drop_retired_desktop_file_system_tables"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="deleted",
            field=models.BooleanField(blank=True, default=False, null=True),
        ),
        migrations.AddField(
            model_name="organization",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        SafeAddIndexConcurrently(
            model_name="organization",
            index=models.Index(
                condition=models.Q(("deleted", True)),
                fields=["id"],
                name="org_deleted_id_idx",
            ),
        ),
    ]
