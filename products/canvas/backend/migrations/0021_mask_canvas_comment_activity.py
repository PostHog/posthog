from collections import defaultdict

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.models import Q

CANVAS_COMMENT_SCOPES = ("canvas", "desktop_canvas")


def mask_canvas_comment_activity(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Comment = apps.get_model("posthog", "Comment")
    ActivityLog = apps.get_model("posthog", "ActivityLog")
    root_ids_by_team: dict[int, list[str]] = defaultdict(list)
    for team_id, comment_id in Comment.objects.filter(
        scope__in=CANVAS_COMMENT_SCOPES, source_comment__isnull=True
    ).values_list("team_id", "id"):
        root_ids_by_team[team_id].append(str(comment_id))

    for team_id, root_ids in root_ids_by_team.items():
        rows = ActivityLog.objects.filter(team_id=team_id).filter(
            Q(scope__in=CANVAS_COMMENT_SCOPES) | Q(scope="Comment", item_id__in=root_ids)
        )
        for row in rows.only("id", "detail"):
            changes = (row.detail or {}).get("changes") or []
            masked = False
            for change in changes:
                if isinstance(change, dict) and change.get("field") == "content" and change.get("after") != "masked":
                    change["after"] = "masked"
                    masked = True
            if masked:
                row.save(update_fields=["detail"])


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0020_alter_canvas_channel"),
        ("posthog", "1385_add_data_deletion_submission_id_constraint"),
    ]

    operations = [
        migrations.RunPython(mask_canvas_comment_activity, migrations.RunPython.noop),
    ]
