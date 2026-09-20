from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # posthog_activitylog is large and write-heavy, and its writes run inline in the request that
    # triggered them, so every index here is latency a user waits for. Build and drop CONCURRENTLY
    # to keep the table readable and writable throughout, which needs atomic = False.
    #
    # The four replacements below re-create an existing index without its partial predicate. Each
    # one is added under a new name before the old one is dropped, so no read path loses its index
    # for the length of a build.
    atomic = False

    dependencies = [
        ("posthog", "1368_sessionrecording_untrack_lts_fields"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["organization_id", "scope", "-created_at"],
                name="idx_alog_org_scope_time",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["team_id", "activity", "scope", "user"],
                name="idx_alog_team_act_scope_user",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["team_id", "scope", "-created_at"],
                name="idx_alog_team_scope_time",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["team_id", "scope", "activity", "-created_at"],
                name="idx_alog_team_scope_act_time",
            ),
        ),
        SafeRemoveIndexConcurrently(model_name="activitylog", name="idx_alog_org_scope_created_at"),
        SafeRemoveIndexConcurrently(model_name="activitylog", name="idx_alog_team_act_scope_usr"),
        SafeRemoveIndexConcurrently(model_name="activitylog", name="idx_alog_team_scope_created"),
        SafeRemoveIndexConcurrently(model_name="activitylog", name="idx_alog_team_scp_act_crtd"),
        # `(organization_id) WHERE detail IS NOT NULL AND jsonb_typeof(detail) = 'object'`. Nothing
        # queries that predicate, and the organization_id lookups that do run are already served by
        # idx_alog_org_created_at and idx_alog_org_scope_time.
        SafeRemoveIndexConcurrently(model_name="activitylog", name="idx_alog_org_detail_exists"),
        # The GIN on `detail`. A jsonb_path_ops entry is written per root-to-leaf path, so a row
        # holding a list of changes costs more index maintenance than every B-tree above it put
        # together. It serves one read: the staff-only AI-training opt-in panel, whose organization
        # + scope + item_id filter idx_alog_org_scope_time narrows to a handful of rows before the
        # containment is ever evaluated.
        SafeRemoveIndexConcurrently(model_name="activitylog", name="idx_alog_detail_gin_path_ops"),
    ]
