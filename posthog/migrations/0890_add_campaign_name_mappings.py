# Generated migration

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0889_add_schema_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="teammarketinganalyticsconfig",
            name="campaign_name_mappings",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Maps clean campaign names to lists of raw UTM values per data source",
                null=False,
            ),
        ),
    ]
