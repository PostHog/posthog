from django.db import migrations


class Migration(migrations.Migration):
    """
    Out-of-band CREATE INDEX CONCURRENTLY for User.onboarding_delegated_to_invite_id.

    posthog_user is a large, hot table read/written by multiple services (Rust feature-flags
    does INNER JOIN posthog_user). A plain `AddField` with `db_index=True` would emit a
    blocking CREATE INDEX that can exceed `lock_timeout` during deploy. The FK field is
    declared with `db_index=False`; we add a partial index concurrently here so it can be
    built without holding a long lock on posthog_user.

    We drop/recreate the index name instead of CREATE ... IF NOT EXISTS so interrupted
    prior concurrent builds (which can leave an invalid index artifact) don't get silently
    accepted as success.

    Operational notes:
    - transient behavior: between DROP and CREATE there can be a brief window without this
      index while the migration runs.
    - rollback: reverse migration drops the index concurrently; it does not recreate any prior
      invalid artifact, and re-applying this migration will rebuild the index.
    """

    atomic = False

    dependencies = [
        ("posthog", "1120_onboarding_delegation_fields"),
    ]

    operations = [
        migrations.RunSQL(
            sql='DROP INDEX CONCURRENTLY IF EXISTS "posthog_user_onboarding_delegated_to_invite_id_idx"',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                '"posthog_user_onboarding_delegated_to_invite_id_idx" '
                'ON "posthog_user" ("onboarding_delegated_to_invite_id") '
                'WHERE "onboarding_delegated_to_invite_id" IS NOT NULL'
            ),
            reverse_sql=('DROP INDEX CONCURRENTLY IF EXISTS "posthog_user_onboarding_delegated_to_invite_id_idx"'),
        ),
    ]
