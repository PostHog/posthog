from django.db import migrations, models


class Migration(migrations.Migration):
    """Add unique constraint on domain (non-blocking).

    Step 1: CREATE UNIQUE INDEX CONCURRENTLY (no table lock).
    Step 2: ADD CONSTRAINT ... UNIQUE USING INDEX (instant, promotes existing index).
    """

    atomic = False

    dependencies = [
        ("conversations", "0025_email_channel"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "unique_email_domain"
                ON "posthog_conversations_email_config" ("domain");
            """,
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "unique_email_domain";',
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="teamconversationsemailconfig",
                    constraint=models.UniqueConstraint(
                        fields=["domain"],
                        name="unique_email_domain",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_conversations_email_config"
                            ADD CONSTRAINT "unique_email_domain"
                            UNIQUE USING INDEX "unique_email_domain";
                    """,
                    reverse_sql='ALTER TABLE "posthog_conversations_email_config" DROP CONSTRAINT IF EXISTS "unique_email_domain";',
                ),
            ],
        ),
    ]
