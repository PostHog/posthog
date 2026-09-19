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
                fields=["team_id", "is_materialized"],
                name="dwsavedquery_team_live_matvw",
                condition=~models.Q(deleted=True),
            ),
        ),
    ]
