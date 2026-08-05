from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1290_backfill_identity_provider_config_identifiers")]

    operations = [
        migrations.AddField(
            model_name="oauthaccesstoken",
            name="sandbox_task_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
