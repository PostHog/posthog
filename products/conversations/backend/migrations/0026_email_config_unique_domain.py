from django.db import migrations


class Migration(migrations.Migration):
    """Create unique index concurrently (non-blocking) on domain."""

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
    ]
