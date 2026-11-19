from django.db import migrations

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("posthog", "1433_integrationrepositorycacheentry_activity")]

    # Both indexes are partial on `jsonb_typeof(detail) = 'object'`, a predicate no activity log
    # query carries, so the planner can never use them.
    # Migrations 0850 and 0851 built them with raw SQL. Django state compiles the same condition
    # (`detail__jsonb_typeof`) to a JSON key lookup, so `SafeRemoveIndexConcurrently` would rebuild
    # a different index on rollback. The `where` arguments copy the SQL from 0850 and 0851.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(model_name="activitylog", name="idx_alog_org_scope_created_at"),
                migrations.RemoveIndex(model_name="activitylog", name="idx_alog_org_detail_exists"),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="idx_alog_org_scope_created_at",
                    table_name="posthog_activitylog",
                    columns="(organization_id, scope, created_at DESC)",
                    where="WHERE detail IS NOT NULL AND jsonb_typeof(detail) = 'object'",
                ),
                DropIndexConcurrently(
                    index_name="idx_alog_org_detail_exists",
                    table_name="posthog_activitylog",
                    columns="(organization_id)",
                    where="WHERE detail IS NOT NULL AND jsonb_typeof(detail) = 'object'",
                ),
            ],
        ),
    ]
