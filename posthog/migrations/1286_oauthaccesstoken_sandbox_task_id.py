from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1285_drop_desktop_file_system")]

    operations = [
        migrations.AddField(
            model_name="oauthaccesstoken",
            name="sandbox_task_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
