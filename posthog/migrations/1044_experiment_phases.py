from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1043_add_15_minute_interval_to_batch_exports")]

    operations = [
        migrations.AddField(
            model_name="experiment",
            name="phases",
            field=models.JSONField(blank=True, default=list, null=True),
        ),
    ]
