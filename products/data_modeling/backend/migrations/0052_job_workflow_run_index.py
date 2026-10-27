from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("data_modeling", "0051_job_usage_indexes")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datamodelingjob",
            index=models.Index(fields=["team", "workflow_id", "workflow_run_id"], name="dmjob_workflow_run"),
        ),
    ]
