from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("posthog", "1433_integrationrepositorycacheentry_activity")]

    # Both indexes are partial on `jsonb_typeof(detail) = 'object'`, a predicate no activity log
    # query carries, so the planner can never use them. They only add write cost to every insert.
    operations = [
        SafeRemoveIndexConcurrently(
            model_name="activitylog",
            name="idx_alog_org_scope_created_at",
        ),
        SafeRemoveIndexConcurrently(
            model_name="activitylog",
            name="idx_alog_org_detail_exists",
        ),
    ]
