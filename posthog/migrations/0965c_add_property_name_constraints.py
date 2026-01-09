from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Step 3: Make property_name NOT NULL and add constraints/indexes.
    Uses AddIndexConcurrently which requires atomic=False.
    """

    atomic = False

    dependencies = [
        ("posthog", "0965b_populate_property_name"),
    ]

    operations = [
        # Make property_name NOT NULL
        migrations.AlterField(
            model_name="materializedcolumnslot",
            name="property_name",
            field=models.CharField(max_length=400),
        ),
        # Add new constraint on property_name
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.UniqueConstraint(
                fields=("team", "property_name"),
                name="unique_team_property_name",
            ),
        ),
        # Add new index on property_name (concurrent to avoid locks)
        AddIndexConcurrently(
            model_name="materializedcolumnslot",
            index=models.Index(
                fields=["team", "property_name"],
                name="posthog_mat_team_pn_idx",
            ),
        ),
        # Add conditional constraint for DMAT slots
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.UniqueConstraint(
                fields=("team", "property_type", "slot_index"),
                name="unique_team_property_type_slot_index_dmat",
                condition=models.Q(materialization_type="dmat"),
            ),
        ),
        # Add conditional check constraint for slot_index (only validates for DMAT)
        migrations.AddConstraint(
            model_name="materializedcolumnslot",
            constraint=models.CheckConstraint(
                name="valid_slot_index_dmat",
                check=models.Q(materialization_type="eav")
                | (models.Q(slot_index__gte=0) & models.Q(slot_index__lte=9)),
            ),
        ),
    ]
