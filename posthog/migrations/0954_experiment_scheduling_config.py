from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0953_create_core_event"),
    ]

    operations = [
        migrations.AddField(
            model_name="experiment",
            name="scheduling_config",
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
    ]
