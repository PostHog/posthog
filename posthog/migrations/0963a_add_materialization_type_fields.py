from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Step 1: Add new fields (safe, no data migration).
    """

    dependencies = [
        ("posthog", "0962_webanalyticsfilterpreset"),
    ]

    operations = [
        # Add materialization_type field with default
        migrations.AddField(
            model_name="materializedcolumnslot",
            name="materialization_type",
            field=models.CharField(
                max_length=10,
                choices=[
                    ("dmat", "Dynamic Materialized Column"),
                    ("eav", "EAV Table"),
                ],
                default="dmat",
            ),
        ),
        # Add property_name column (nullable initially)
        migrations.AddField(
            model_name="materializedcolumnslot",
            name="property_name",
            field=models.CharField(max_length=400, null=True),
        ),
    ]
