from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1097_add_is_pending_deletion_to_organization"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="ingested_live_event",
            field=models.BooleanField(default=False),
        ),
    ]
