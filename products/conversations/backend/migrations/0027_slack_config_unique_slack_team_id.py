from django.db import migrations, models


class Migration(migrations.Migration):
    """Create partial unique index concurrently (non-blocking) on slack_team_id.

    Excludes NULL rows since every team gets an auto-created config via
    register_team_extension_signal with slack_team_id=NULL.
    """

    atomic = False

    dependencies = [
        ("conversations", "0026_email_config_unique_domain"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "unique_slack_team_id"
                ON "posthog_conversations_slack_config" ("slack_team_id")
                WHERE "slack_team_id" IS NOT NULL;
            """,
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "unique_slack_team_id";',
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="teamconversationsslackconfig",
                    constraint=models.UniqueConstraint(
                        fields=["slack_team_id"],
                        condition=models.Q(slack_team_id__isnull=False),
                        name="unique_slack_team_id",
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
