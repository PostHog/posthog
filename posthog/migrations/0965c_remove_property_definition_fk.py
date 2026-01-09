import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Step 3: Remove old constraints and make property_definition nullable.
    The column will be removed in a future migration after this deploys.
    """

    dependencies = [
        ("posthog", "0965b_populate_property_name"),
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
        # Remove old unconditional constraint (replaced by conditional one in 0965b)
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="unique_team_property_type_slot_index",
        ),
        # Remove old unconditional check constraint (replaced by conditional one in 0965b)
        migrations.RemoveConstraint(
            model_name="materializedcolumnslot",
            name="valid_slot_index",
        ),
        # Make property_definition nullable (instead of removing it)
        # This preserves backwards compatibility - column removal will be in a future migration
        migrations.AlterField(
            model_name="materializedcolumnslot",
            name="property_definition",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="materialized_column_slots",
                related_query_name="materialized_column_slot",
                to="posthog.propertydefinition",
            ),
        ),
    ]
