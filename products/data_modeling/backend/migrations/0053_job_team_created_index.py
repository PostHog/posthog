from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("data_modeling", "0052_job_workflow_run_index")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datamodelingjob",
            index=models.Index(fields=["team", "-created_at"], name="dmjob_team_created"),
        ),
    ]
