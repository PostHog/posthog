from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1152_fix_device_bucketing_persist_across_auth")]

    operations = [
        migrations.AddField(
            model_name="team",
            name="toolbar_disabled",
            field=models.BooleanField(blank=True, default=False, null=True),
        ),
    ]
