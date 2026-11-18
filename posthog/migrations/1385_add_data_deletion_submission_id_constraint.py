from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("posthog", "1384_add_data_deletion_submission_id")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="datadeletionrequest",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(submission_id__isnull=False),
                        fields=("team_id", "submission_id"),
                        name="ddr_team_submission_id_uniq",
                    ),
                )
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="ddr_team_submission_id_uniq",
                    table_name="posthog_datadeletionrequest",
                    columns="(team_id, submission_id) WHERE submission_id IS NOT NULL",
                    unique=True,
                )
            ],
        )
    ]
