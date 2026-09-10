from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("alerts", "0006_alter_alert_insight_alter_alert_team_and_more")]

    operations = [
        migrations.AddField(
            model_name="alertconfiguration",
            name="forecast_config",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
