from django.db import migrations


class Migration(migrations.Migration):
    # Required for CREATE INDEX CONCURRENTLY — Postgres rejects it inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1129_userintegration"),
    ]

    operations = [
        # The default `db_index=True` on `OrganizationInvite.target_email` is a plain B-tree
        # over the raw column, which Postgres can't use for `target_email__iexact=<value>`
        # (compiles to `UPPER(target_email::text) = UPPER(<value>)`). The lookup powers a
        # SerializerMethodField on `/api/users/@me`, hit on every authenticated page load,
        # and was sequential-scanning the whole invites table. This functional index makes
        # those existing `__iexact` lookups indexable without touching call sites or
        # backfilling stored values.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "posthog_organizationinvite_target_email_lower_idx "
                "ON posthog_organizationinvite (LOWER(target_email))"
            ),
            reverse_sql=(
                "DROP INDEX CONCURRENTLY IF EXISTS "
                "posthog_organizationinvite_target_email_lower_idx"
            ),
        ),
    ]
