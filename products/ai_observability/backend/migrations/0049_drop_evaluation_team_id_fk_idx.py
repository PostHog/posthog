import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("ai_observability", "0048_evaluationbackfill"),
    ]

    operations = [
        # Django's automatic ForeignKey index. Three declared indexes lead with team_id —
        # (team, -created_at, id), (team, enabled) and (team, directory, -created_at, id) —
        # so this index serves no read.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="evaluation",
                    name="team",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
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
