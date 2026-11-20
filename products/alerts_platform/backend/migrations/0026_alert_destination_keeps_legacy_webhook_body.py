from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0025_alert_routes"),
    ]

    operations = [
        migrations.AddField(
            model_name="alertdestination",
            name="keeps_legacy_webhook_body",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
