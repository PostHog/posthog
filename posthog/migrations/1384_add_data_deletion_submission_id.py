from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1383_taggeditem_untrack_legacy_keys")]

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
