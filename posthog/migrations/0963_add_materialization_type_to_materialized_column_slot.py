from django.db import migrations, models


def populate_property_name(apps, schema_editor):
    """Copy property name from property_definition to property_name column."""
    MaterializedColumnSlot = apps.get_model("posthog", "MaterializedColumnSlot")
    for slot in MaterializedColumnSlot.objects.select_related("property_definition").all():
        slot.property_name = slot.property_definition.name
        slot.save(update_fields=["property_name"])


def reverse_populate_property_name(apps, schema_editor):
    """Reverse migration - property_definition already has the data."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0962_webanalyticsfilterpreset"),
    ]

    operations = [
        # Add materialization_type field
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
        # Populate property_name from property_definition
        migrations.RunPython(populate_property_name, reverse_populate_property_name),
        # Make property_name NOT NULL
        migrations.AlterField(
            model_name="materializedcolumnslot",
            name="property_name",
            field=models.CharField(max_length=400),
        ),
        # Remove old constraint
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="unique_team_property_definition",
        ),
        # Remove old index
        migrations.RemoveIndex(
            model_name="materializedcolumnslot",
            name="posthog_mat_team_pr_idx",
        ),
        # Add new constraint
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.UniqueConstraint(
                fields=("team", "property_name"),
                name="unique_team_property_name",
            ),
        ),
        # Add new index
        migrations.AddIndex(
            model_name="materializedcolumnslot",
            index=models.Index(
                fields=["team", "property_name"],
                name="posthog_mat_team_pr_idx",
            ),
        ),
        # Drop the property_definition FK
        migrations.RemoveField(
            model_name="materializedcolumnslot",
            name="property_definition",
        ),
    ]
