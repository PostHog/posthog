from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1377_untrack_superseded_experiment_settings")]

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
