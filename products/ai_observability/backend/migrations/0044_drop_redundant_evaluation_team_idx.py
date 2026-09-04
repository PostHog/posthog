import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("ai_observability", "0043_drop_legacy_dataset_tables"),
    ]

    operations = [
        # Django's default index on the team foreign key. Three of the model's declared
        # indexes already lead with team, so the planner never selects this one. The raw
        # drop keeps the foreign key constraint, which a plain AlterField would drop and
        # re-add.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="evaluation",
                    name="team",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="llm_analytics_evaluation_team_id_6ce3e49f",
                    table_name="llm_analytics_evaluation",
                    columns="(team_id)",
                ),
            ],
        ),
    ]
