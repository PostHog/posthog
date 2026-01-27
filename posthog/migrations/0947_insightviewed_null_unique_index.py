from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # Required for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("posthog", "0946_fix_insightviewed_null_duplicates"),
    ]

    operations = [
        # Add partial unique index to prevent future duplicates.
        # The existing unique constraint on (team_id, user_id, insight_id) doesn't
        # prevent duplicates when team_id and user_id are NULL because PostgreSQL
        # treats NULL != NULL. This partial index enforces uniqueness for that case.
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "posthog_insightviewed_null_team_user_unique"
                ON "posthog_insightviewed" ("insight_id")
                WHERE "team_id" IS NULL AND "user_id" IS NULL
            """,
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "posthog_insightviewed_null_team_user_unique"',
        ),
    ]
