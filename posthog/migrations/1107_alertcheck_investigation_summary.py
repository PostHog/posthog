from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1106_alert_investigation_fields")]

    operations = [
        migrations.AddField(
            model_name="alertcheck",
            name="investigation_summary",
            field=models.TextField(blank=True, null=True),
        ),
    ]
