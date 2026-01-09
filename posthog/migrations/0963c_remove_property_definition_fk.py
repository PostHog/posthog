from django.db import migrations


class Migration(migrations.Migration):
    """
    Step 3: Remove old property_definition FK and associated constraints/indexes.
    Deploy after 0963b is verified working.
    """

    dependencies = [
        ("posthog", "0963b_populate_property_name"),
    ]

    operations = [
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
        # Remove old unconditional constraint (replaced by conditional one in 0963b)
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="unique_team_property_type_slot_index",
        ),
        # Remove old unconditional check constraint (replaced by conditional one in 0963b)
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="valid_slot_index",
        ),
        # Drop the property_definition FK
        migrations.RemoveField(
            model_name="materializedcolumnslot",
            name="property_definition",
        ),
    ]
