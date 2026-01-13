from django.db import migrations


def populate_property_name(apps, schema_editor):
    """Copy property name from property_definition to property_name column using efficient SQL."""
    # First, delete orphaned slots where property_definition is NULL or references a deleted definition.
    # This ensures no NULL property_name values remain before 0965c makes property_name NOT NULL.
    schema_editor.execute(
        """
        DELETE FROM posthog_materializedcolumnslot
        WHERE property_definition_id IS NULL
           OR property_definition_id NOT IN (SELECT id FROM posthog_propertydefinition)
        """
    )
    # Then populate property_name from valid property definitions
    schema_editor.execute(
        """
        UPDATE posthog_materializedcolumnslot AS slot
        SET property_name = pd.name
        FROM posthog_propertydefinition AS pd
        WHERE slot.property_definition_id = pd.id
        """
    )


def reverse_populate_property_name(apps, schema_editor):
    """Reverse migration - property_definition still has the data."""
    pass


class Migration(migrations.Migration):
    """
    Step 2: Data migration only - populate property_name from property_definition FK.
    """

    dependencies = [
        ("posthog", "0965a_add_materialization_type_fields"),
    ]

    operations = [
        migrations.RunPython(populate_property_name, reverse_populate_property_name),
    ]
