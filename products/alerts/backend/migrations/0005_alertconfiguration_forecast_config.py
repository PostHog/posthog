from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0004_squash_2026_09_07_finalize_fks"),
    ]

    operations = [
        migrations.AddField(
            model_name="alertconfiguration",
            name="forecast_config",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
