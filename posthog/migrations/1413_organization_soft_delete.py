from django.db import migrations, models


class Migration(migrations.Migration):
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
    ]
