from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("data_modeling", "0045_node_metric_indexes"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datawarehousesavedquery",
            index=models.Index(
                condition=models.Q(("deleted", True), _negated=True),
                fields=["team_id", "-created_at"],
                name="dwsavedquery_team_live_created",
            ),
        ),
    ]
