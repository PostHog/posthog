from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0097_repin_judges_to_active_key"),
    ]

    operations = [
        # The table stays in Postgres so pods on the previous release keep reading it.
        # Removing the model from state stops Django cascading into it, so its foreign keys must
        # go in the same migration or a team or provider key delete fails at COMMIT.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="EvaluationConfig"),
            ],
            database_operations=[
                DropForeignKey("llm_analytics_evaluationconfig", column=["team_id", "active_provider_key_id"]),
            ],
        ),
    ]
