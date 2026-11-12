from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Take ActionSelectorMatchChange out of Django's state and drop its foreign key to posthog_action.

    The table stays until a later migration drops it with SafeDropTable.

    The foreign key goes now. Once Django cannot see the model, deleting an action stops
    cascading into this table, and the deferred constraint would fail that delete at COMMIT.
    The team key was created with db_constraint=False, so it has no constraint to drop.
    """

    dependencies = [
        ("actions", "0003_actionselectormatchchange"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="actionselectormatchchange",
                    name="unique_selector_match_change_per_step",
                ),
                migrations.DeleteModel(name="ActionSelectorMatchChange"),
            ],
            database_operations=[
                DropForeignKey("actions_actionselectormatchchange", column="action_id"),
            ],
        ),
    ]
