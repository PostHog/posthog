from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1229_teamprovisioningconfig_application_idx")]

    operations = [
        migrations.AddField(
            model_name="duckgresserver",
            name="bucket",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="duckgresserver",
            name="bucket_region",
            field=models.CharField(default="us-east-1", max_length=50),
        ),
    ]
