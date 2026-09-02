"""Soft-delete the auto-created channel home boards.

The channel home is a native client view now, so the seeded home-board
canvases are retired. Soft-delete (recoverable) because they were
system-generated directory listings, not user content; user-created canvases
are untouched. The `is_home` machinery itself is removed in 0008.
"""

from django.db import migrations


def soft_delete_home_canvases(apps, schema_editor):
    Canvas = apps.get_model("canvas", "Canvas")
    Canvas.objects.filter(is_home=True, deleted=False).update(deleted=True)


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0006_require_build_enqueued_at"),
    ]

    operations = [
        migrations.RunPython(soft_delete_home_canvases, migrations.RunPython.noop, elidable=False),
    ]
