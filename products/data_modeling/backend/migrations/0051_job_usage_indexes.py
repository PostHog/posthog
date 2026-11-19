from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("data_modeling", "0050_job_usage")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datamodelingjob",
            index=models.Index(fields=["team", "-last_run_at"], name="dmjob_team_usage_run"),
        ),
        SafeAddIndexConcurrently(
            model_name="datamodelingjob",
            index=models.Index(fields=["last_run_at"], name="dmjob_usage_run"),
        ),
    ]
