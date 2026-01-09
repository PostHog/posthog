from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0962_webanalyticsfilterpreset"),
    ]

    operations = [
        migrations.AddField(
            model_name="exportedasset",
            name="failure_type",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
