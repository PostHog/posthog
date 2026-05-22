from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1175_drop_alertconfiguration_is_calculating_column"),
    ]

    operations = [
        migrations.AddField(
            model_name="activitylog",
            name="ip_address",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
    ]
