from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class _CreateIndexConcurrentlyPlainReverse(CreateIndexConcurrently):
    """
    `CreateIndexConcurrently` with a plain (non-CONCURRENTLY) `database_backwards`.

    `DROP INDEX CONCURRENTLY` cannot run inside a transaction block, but `TestMigrations`
    reverses migrations from inside the test's own wrapping transaction — any test whose
    `migrate_to` sits below this one hits that error the moment it needs to unapply it.
    A plain `DROP INDEX` locks for a moment, not the long build `CREATE` risks, so trading
    away concurrency only on rollback — real ones are rare, and the only other caller is
    this same test harness — costs nothing worth guarding.

    Forward stays untouched: `database_forwards` (CONCURRENTLY, IF NOT EXISTS, invalid-index
    recovery) is fully inherited from `CreateIndexConcurrently`.
    """

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        schema_editor.execute("SET lock_timeout = 0")
        schema_editor.execute("SET statement_timeout = 0")
        schema_editor.execute(f'DROP INDEX IF EXISTS "{self.index_name}"')


class Migration(migrations.Migration):
    """
    posthog_user is a hot table read on virtually every request. CreateIndexConcurrently builds
    with CREATE INDEX CONCURRENTLY (SHARE UPDATE EXCLUSIVE, doesn't block reads/writes) rather than
    a plain AddIndex, which takes an ACCESS EXCLUSIVE lock. Raw SQL, not a tracked `models.Index`,
    matching the existing 1138_onboarding_delegated_to_invite_index precedent for this table: User
    has never carried a Meta.indexes list, and this doesn't start one.

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
        _CreateIndexConcurrentlyPlainReverse(
            index_name="user_stripped_alias_idx",
            table_name="posthog_user",
            columns="(regexp_replace(lower(email), '\\+[^@]*@', '@'))",
        ),
    ]
