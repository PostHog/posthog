from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Each index is added under a new name before its predecessor is dropped, so no read path
    # loses an index for the length of a concurrent build on a large table.
    atomic = False

    dependencies = [
        ("posthog", "1376_taggeditem_untrack_legacy_keys"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["team_id", "activity", "scope", "user"],
                name="idx_alog_team_act_scp_usr_all",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["team_id", "scope", "-created_at"],
                name="idx_alog_team_scope_crtd_all",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["team_id", "scope", "activity", "-created_at"],
                name="idx_alog_team_scp_act_crtd_all",
            ),
        ),
        SafeRemoveIndexConcurrently(
            model_name="activitylog",
            name="idx_alog_team_act_scope_usr",
        ),
        SafeRemoveIndexConcurrently(
            model_name="activitylog",
            name="idx_alog_team_scope_created",
        ),
        SafeRemoveIndexConcurrently(
            model_name="activitylog",
            name="idx_alog_team_scp_act_crtd",
        ),
    ]
