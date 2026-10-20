from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def rename_comment_scope(apps: Apps, from_scope: str, to_scope: str) -> None:
    for model_name in ("Comment", "CommentSlackThread"):
        apps.get_model("posthog", model_name).objects.filter(scope=from_scope).update(scope=to_scope)


def forwards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    rename_comment_scope(apps, "desktop_canvas", "canvas")


def backwards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    rename_comment_scope(apps, "canvas", "desktop_canvas")


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1389_teameventvolume"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
