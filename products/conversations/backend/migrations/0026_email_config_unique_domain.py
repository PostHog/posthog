from django.db import migrations, models


class Migration(migrations.Migration):
    """Create unique index concurrently (non-blocking) on domain.

    The unique index enforces the constraint at the DB level.
    SeparateDatabaseAndState syncs Django's model state without extra DDL.
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
            database_operations=[],
        ),
    ]
