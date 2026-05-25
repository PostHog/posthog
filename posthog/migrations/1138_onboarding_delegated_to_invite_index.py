from django.db import migrations


class Migration(migrations.Migration):
    """
    Out-of-band CREATE INDEX CONCURRENTLY for User.onboarding_delegated_to_invite_id.

    posthog_user is a large, hot table read/written by multiple services (Rust feature-flags
    does INNER JOIN posthog_user). A plain `AddField` with `db_index=True` would emit a
    blocking CREATE INDEX that can exceed `lock_timeout` during deploy. The FK field is
    declared with `db_index=False` in the model; we add a partial index concurrently here
    so it can be built without holding a long lock on posthog_user.

    Partial index (WHERE column IS NOT NULL) matches the query patterns in
    `OrganizationInvite._unsuppress_delegator_onboarding_on_invite_delete` and
    `mark_delegators_accepted`, both of which filter by a non-null FK value.

    If a previous deploy was interrupted mid-CREATE, the resulting invalid index needs to
    be dropped/reindexed manually (via `REINDEX INDEX CONCURRENTLY`) before re-running. We
    no longer DROP ... CONCURRENTLY inside this migration because doing so on every run
    opens a window where queries fall back to a sequential scan on posthog_user.
    """

    atomic = False

    dependencies = [("posthog", "1137_onboarding_delegation_fk")]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                '"posthog_user_onboarding_delegated_to_invite_id_idx" '
                'ON "posthog_user" ("onboarding_delegated_to_invite_id") '
                'WHERE "onboarding_delegated_to_invite_id" IS NOT NULL'
            ),
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "posthog_user_onboarding_delegated_to_invite_id_idx"',
        ),
    ]
