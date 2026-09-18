from django.db import migrations

from posthog.migration_helpers import DropIndexConcurrently

# Both indexes are partial on `jsonb_typeof(detail) = 'object'`, which the ORM cannot model, so
# migrations 0850 and 0851 built them from raw SQL. The Django `Index` they recorded in state
# compiles that predicate to the JSON key lookup `detail -> 'jsonb_typeof'` instead, which matches
# almost no row. A state-driven reverse would rebuild that near-empty index, so each drop carries
# its own reverse SQL and a rollback restores the index it dropped.
DETAIL_IS_OBJECT = "WHERE detail IS NOT NULL AND jsonb_typeof(detail) = 'object'"


class Migration(migrations.Migration):
    # posthog_activitylog is large and write-heavy, so drop the B-trees CONCURRENTLY to avoid an
    # ACCESS EXCLUSIVE lock on the table. Concurrent drops can't run in a transaction, hence
    # atomic = False.
    atomic = False

    dependencies = [
        ("posthog", "1368_sessionrecording_untrack_lts_fields"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(model_name="activitylog", name="idx_alog_org_detail_exists"),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="idx_alog_org_detail_exists",
                    table_name="posthog_activitylog",
                    columns="(organization_id)",
                    where=DETAIL_IS_OBJECT,
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(model_name="activitylog", name="idx_alog_org_scope_created_at"),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="idx_alog_org_scope_created_at",
                    table_name="posthog_activitylog",
                    columns="(organization_id, scope, created_at DESC)",
                    where=DETAIL_IS_OBJECT,
                ),
            ],
        ),
    ]
