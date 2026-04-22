# Generated manually for schedule_restriction on alerts

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1086_alter_teammarketinganalyticsconfig_attribution_mode")]

    operations = [
        migrations.AddField(
            model_name="alertconfiguration",
            name="schedule_restriction",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
