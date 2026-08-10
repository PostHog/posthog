from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrentlyPlainReverse


class Migration(migrations.Migration):
    """
    posthog_user is a hot table read on virtually every request. CreateIndexConcurrentlyPlainReverse
    builds with CREATE INDEX CONCURRENTLY (SHARE UPDATE EXCLUSIVE, doesn't block reads/writes) rather
    than a plain AddIndex, which takes an ACCESS EXCLUSIVE lock. Raw SQL, not a tracked `models.Index`,
    matching the existing 1138_onboarding_delegated_to_invite_index precedent for this table: User
    has never carried a Meta.indexes list, and this doesn't start one.

    The plain (non-CONCURRENTLY) reverse — see CreateIndexConcurrentlyPlainReverse's docstring — is
    needed because TestMigrations (posthog/test/base.py) reverses migrations inside the test's own
    transaction, and any un-skipped test targeting 1296 or earlier has to unapply this migration to
    get there.

    The index is not yet used by any query in this migration — EmailValidationHelper.user_exists_with_stripped_alias
    still filters via iexact/istartswith/iendswith. A follow-up change rewrites that lookup to filter
    on this same expression, turning its full-table scan into an index scan. Landing the index first,
    on its own, lets it finish building before that lookup starts relying on it.
    """

    atomic = False

    dependencies = [
        ("posthog", "1296_backfill_cimd_verification_token_url"),
    ]

    operations = [
        CreateIndexConcurrentlyPlainReverse(
            index_name="user_stripped_alias_idx",
            table_name="posthog_user",
            columns="(regexp_replace(lower(email), '\\+[^@]*@', '@'))",
        ),
    ]
