from django.db import migrations, models


def populate_property_name(apps, schema_editor):
    """Copy property name from property_definition to property_name column using efficient SQL."""
    # Use raw SQL for efficient bulk update instead of row-by-row Python loop
    schema_editor.execute(
        """
        UPDATE posthog_materializedcolumnslot AS slot
        SET property_name = pd.name
        FROM posthog_propertydefinition AS pd
        WHERE slot.property_definition_id = pd.id
        """
    )


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
        # Remove old constraint on property_definition
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="unique_team_property_definition",
        ),
        # Remove old index on property_definition
        migrations.RemoveIndex(
            model_name="materializedcolumnslot",
            name="posthog_mat_team_pr_idx",
        ),
        # Add new constraint on property_name
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.UniqueConstraint(
                fields=("team", "property_name"),
                name="unique_team_property_name",
            ),
        ),
        # Add new index on property_name
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
        # Remove old unconditional constraint (applies to all rows)
        # Replace with conditional constraint that only applies to DMAT slots
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="unique_team_property_type_slot_index",
        ),
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.UniqueConstraint(
                fields=("team", "property_type", "slot_index"),
                name="unique_team_property_type_slot_index_dmat",
                condition=models.Q(materialization_type="dmat"),
            ),
        ),
        # Remove old unconditional check constraint
        # Replace with conditional check that only validates slot_index for DMAT
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="valid_slot_index",
        ),
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.CheckConstraint(
                name="valid_slot_index_dmat",
                check=models.Q(materialization_type="eav")
                | (models.Q(slot_index__gte=0) & models.Q(slot_index__lte=9)),
            ),
        ),
    ]
