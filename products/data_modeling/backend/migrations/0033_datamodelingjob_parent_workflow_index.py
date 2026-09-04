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
            index=models.Index(
                fields=["team", "parent_workflow_id"],
                name="datamodelingjob_team_parentwf",
                condition=models.Q(parent_workflow_id__isnull=False),
            ),
        ),
    ]
