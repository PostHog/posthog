from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1217_project_is_pending_deletion"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="ingested_production_event_last_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
