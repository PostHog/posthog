# Generated manually to add product scoping to billing alerts.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing_alerts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="billingalertconfiguration",
            name="product",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="billingalertevent",
            name="product",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
