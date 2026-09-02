"""Retire the desktop file-system surface.

The desktop tree's contents were migrated into first-class models by
``canvas.0003_migrate_desktop_tree`` (channels, canvases, channel
instructions, stars, task-channel backfill). This migration removes the old
models from Django state while leaving physical cleanup for a later deployment.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1284_organization_enforce_verified_domains"),
        ("canvas", "0003_migrate_desktop_tree"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name="FileSystemFolderContextGeneration"),
                migrations.DeleteModel(name="FileSystemFolderInstructions"),
            ],
        )
    ]
