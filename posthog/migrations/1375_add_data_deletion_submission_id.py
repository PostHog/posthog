from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1374_teamheatmapconfig_capture_enforcement_started_at_and_more")]

    operations = [
        migrations.AddField(
            model_name="datadeletionrequest",
            name="submission_id",
            field=models.UUIDField(
                blank=True,
                help_text="Client-generated identifier used to deduplicate self-service submissions.",
                null=True,
            ),
        ),
    ]
