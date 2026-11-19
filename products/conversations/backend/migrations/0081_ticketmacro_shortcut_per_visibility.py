from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently, DropIndexConcurrently

TABLE = "posthog_conversations_ticket_macro"


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("conversations", "0080_ticketmacro_visibility"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(model_name="ticketmacro", name="conv_macro_team_shortcut_uniq"),
                migrations.AddConstraint(
                    model_name="ticketmacro",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(shortcut__isnull=False, visibility="shared"),
                        fields=("team", "shortcut"),
                        name="conv_macro_shared_shortcut_uniq",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="ticketmacro",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(shortcut__isnull=False, visibility="personal"),
                        fields=("team", "created_by", "shortcut"),
                        name="conv_macro_personal_shortcut_uniq",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="conv_macro_shared_shortcut_uniq",
                    table_name=TABLE,
                    columns='("team_id", "shortcut")',
                    unique=True,
                    where='WHERE ("shortcut" IS NOT NULL AND "visibility" = \'shared\')',
                ),
                CreateIndexConcurrently(
                    index_name="conv_macro_personal_shortcut_uniq",
                    table_name=TABLE,
                    columns='("team_id", "created_by_id", "shortcut")',
                    unique=True,
                    where='WHERE ("shortcut" IS NOT NULL AND "visibility" = \'personal\')',
                ),
                DropIndexConcurrently(
                    index_name="conv_macro_team_shortcut_uniq",
                    table_name=TABLE,
                    columns='("team_id", "shortcut")',
                    unique=True,
                    where='WHERE "shortcut" IS NOT NULL',
                ),
            ],
        ),
    ]
