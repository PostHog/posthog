from django.db import migrations


class Migration(migrations.Migration):
    """Drop the ducklake tables 1242 left behind.

    1242 took DuckLakeCatalog and DuckLakeBackfill out of Django state and kept their tables, so
    old workers could still read them through a rolling deploy. The follow-up it names never
    landed. The tables are still here, still holding the connection details for a warehouse that
    moved onto DuckgresServer in 1241, and still carrying foreign keys to posthog_team,
    posthog_organization and posthog_user.

    Dropping only those keys would be worse than leaving them. A team or organization delete
    fails at COMMIT today, because the constraints are DEFERRABLE INITIALLY DEFERRED with NO
    ACTION and Django no longer cascades into a relation it cannot see. Take the keys away on
    their own and the delete succeeds while the row survives, so a deleted tenant leaves its
    database host, username, password and cross-account role behind with nothing pointing at
    them. The tables have to go with the keys.

    DROP TABLE takes ACCESS EXCLUSIVE on every table these foreign keys reference, and two of
    those are hot. The statement runs under a short lock_timeout so it fails fast and bin/migrate
    retries, rather than queueing that lock for the whole MIGRATE_LOCK_TIMEOUT window while every
    query arriving behind it waits.
    """

    dependencies = [
        ("posthog", "1352_email_lookup_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                SET LOCAL lock_timeout = '2s';
                DROP TABLE IF EXISTS posthog_ducklakecatalog, posthog_ducklakebackfill;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
