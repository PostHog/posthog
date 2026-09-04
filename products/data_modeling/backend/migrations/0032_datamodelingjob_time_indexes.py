from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("data_modeling", "0031_datamodelingjob_run_mode"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datamodelingjob",
            index=models.Index(fields=["saved_query", "-created_at"], name="datamodelingjob_sq_created_at"),
        ),
        SafeAddIndexConcurrently(
            model_name="datamodelingjob",
            index=models.Index(fields=["saved_query", "-last_run_at"], name="datamodelingjob_sq_last_run_at"),
        ),
        SafeAddIndexConcurrently(
            model_name="datamodelingjob",
            index=models.Index(fields=["team", "-created_at"], name="datamodelingjob_team_created"),
        ),
    ]
