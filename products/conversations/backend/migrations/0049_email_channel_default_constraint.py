from django.db import migrations, models


class Migration(migrations.Migration):
    # CREATE UNIQUE INDEX CONCURRENTLY cannot run inside a transaction
    atomic = False

    dependencies = [
        ("conversations", "0048_backfill_default_email_channel"),
    ]

    operations = [
        # Create the partial unique index concurrently (no table lock), while telling Django state
        # the model now has the constraint. The index name matches what the UniqueConstraint would
        # generate, so there's no state drift.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="emailchannel",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("is_default", True)),
                        fields=("team",),
                        name="unique_default_email_channel_per_team",
                    ),
                ),
            ],
            database_operations=[
                # Single statement per RunSQL — CREATE INDEX CONCURRENTLY can't run in a transaction,
                # and multiple statements in one RunSQL get wrapped in one
                migrations.RunSQL(
                    sql=(
                        'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "unique_default_email_channel_per_team" '
                        'ON "posthog_conversations_email_channel" ("team_id") WHERE "is_default";'
                    ),
                    reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "unique_default_email_channel_per_team";',
                ),
            ],
        ),
    ]
