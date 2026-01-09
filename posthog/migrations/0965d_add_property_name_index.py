from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Step 4: Add index on property_name concurrently.
    Requires atomic=False for CONCURRENTLY operations.
    """

    atomic = False

    dependencies = [
        ("posthog", "0965c_add_property_name_constraints"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="materializedcolumnslot",
            index=models.Index(
                fields=["team", "property_name"],
                name="posthog_mat_team_pn_idx",
            ),
        ),
    ]
