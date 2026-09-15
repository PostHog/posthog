from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("data_modeling", "0041_datamodelingjob_sq_engine_run_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datawarehousesavedquery",
            index=models.Index(
                condition=models.Q(("is_materialized", True), models.Q(("deleted", True), _negated=True)),
                fields=["team_id"],
                name="dwsavedquery_team_matview",
            ),
        ),
    ]
