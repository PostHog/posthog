from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0820_organization_allow_publicly_shared_resources"),
    ]

    operations = [
        migrations.AddField(
            model_name="batchimport",
            name="backoff_attempt",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="batchimport",
            name="backoff_until",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
