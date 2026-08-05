from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1286_cleanup_orphaned_identity_provider_configs")]

    operations = [
        migrations.AddField(
            model_name="oauthaccesstoken",
            name="sandbox_task_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
