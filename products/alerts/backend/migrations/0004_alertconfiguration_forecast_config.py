from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0003_alter_alertconfiguration_calculation_interval"),
    ]

    operations = [
        migrations.AddField(
            model_name="alertconfiguration",
            name="forecast_config",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
