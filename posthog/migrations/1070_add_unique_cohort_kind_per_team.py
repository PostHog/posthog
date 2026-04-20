from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False  # Required for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("posthog", "1069_datadeletionrequest"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="cohort",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("deleted", False), kind__isnull=False),
                        fields=("team", "kind"),
                        name="unique_cohort_kind_per_team",
                    ),
                ),
            ],
            database_operations=[
                # CREATE UNIQUE INDEX CONCURRENTLY does not hold an exclusive lock
                # on the table — it only takes a ShareUpdateExclusiveLock, which
                # allows concurrent reads AND writes to continue while the index is
                # built in the background. The migration must be non-atomic
                # (atomic = False) because CONCURRENTLY cannot run inside a
                # transaction.
                migrations.RunSQL(
                    sql="""
                        CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "unique_cohort_kind_per_team"
                        ON "posthog_cohort" ("team_id", "kind")
                        WHERE "kind" IS NOT NULL AND "deleted" = false
                    """,
                    reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "unique_cohort_kind_per_team"',
                ),
            ],
        ),
    ]
