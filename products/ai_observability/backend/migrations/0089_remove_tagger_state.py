from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Take Tagger out of Django's state and drop its foreign keys.

    Taggers were replaced by categorical evaluations, and nothing reads or writes the table anymore.
    The table stays until a later migration drops it with SafeDropTable.

    The foreign keys go now. Once Django cannot see the model, deleting a team, a user or a model
    configuration stops cascading into this table, and the deferred constraints would fail that
    delete at COMMIT. Two keys point at hot tables, so each drop commits on its own to keep the
    parent locks short.
    """

    atomic = False

    dependencies = [
        ("ai_observability", "0088_eval_suggestion_turned_off"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="Tagger")],
            database_operations=[
                DropForeignKey("llm_analytics_tagger", column="team_id"),
                DropForeignKey("llm_analytics_tagger", column="created_by_id"),
                DropForeignKey("llm_analytics_tagger", column="model_configuration_id"),
            ],
        ),
    ]
