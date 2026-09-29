from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

BATCH_SIZE = 1000


def rename_comment_scope(apps: Apps, from_scope: str, to_scope: str) -> None:
    Comment = apps.get_model("posthog", "Comment")
    ids = list(Comment.objects.filter(scope=from_scope).values_list("id", flat=True))
    for start in range(0, len(ids), BATCH_SIZE):
        Comment.objects.filter(id__in=ids[start : start + BATCH_SIZE]).update(scope=to_scope)


def forwards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    rename_comment_scope(apps, "desktop_canvas", "canvas")


def backwards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    rename_comment_scope(apps, "canvas", "desktop_canvas")


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1385_add_data_deletion_submission_id_constraint"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
