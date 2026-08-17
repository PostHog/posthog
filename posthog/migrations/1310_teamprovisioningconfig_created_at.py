from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1309_integration_kind_ext_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="teamprovisioningconfig",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
    ]
