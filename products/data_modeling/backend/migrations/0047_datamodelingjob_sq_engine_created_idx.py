from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("data_modeling", "0046_dwsavedquery_team_live_created_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datamodelingjob",
            index=models.Index(fields=["saved_query", "engine", "-created_at"], name="datamodelingjob_sq_engine_crt"),
        ),
    ]
