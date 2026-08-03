"""Retire the desktop file-system surface.

The desktop tree's contents were migrated into first-class models by
``canvas.0002_migrate_desktop_tree`` (channels, canvases, channel
instructions, stars, task-channel backfill); this migration deletes the
now-unreferenced desktop rows and drops the folder-instruction models the
channel-scoped equivalents replaced. The web-surface file system is untouched.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1270_untrack_provisioning_auth_columns"),
        ("canvas", "0002_migrate_desktop_tree"),
    ]

    operations = [
        migrations.DeleteModel(name="FileSystemFolderContextGeneration"),
        migrations.DeleteModel(name="FileSystemFolderInstructions"),
        # Raw SQL, not queryset .delete(): the ORM path dispatches global
        # post-delete signal receivers per row (cache refreshes and the like),
        # which a migration must not do — and there is nothing to cascade to.
        migrations.RunSQL(
            [
                "DELETE FROM posthog_filesystem WHERE surface = 'desktop'",
                "DELETE FROM posthog_filesystemshortcut WHERE surface = 'desktop'",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
