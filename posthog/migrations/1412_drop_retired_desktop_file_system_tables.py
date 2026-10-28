from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    """Drop the desktop file-system tables 1285 left behind.

    1285 took FileSystemFolderInstructions and FileSystemFolderContextGeneration out of Django state and
    kept their tables, with their foreign keys to posthog_team, posthog_user and posthog_filesystem.
    The keys are DEFERRABLE INITIALLY DEFERRED, and Django no longer cascades into these tables, so
    deleting a team, a user or a folder that a row references fails at COMMIT, and the team deletion
    workflow retries until it gives up.

    canvas.0003_migrate_desktop_tree copies these rows into the canvas and tasks models, so a database
    that has not run it yet must run it before the tables go. Databases created from the squashed
    history never had these tables, and SafeDropTable skips a table that does not exist.
    """

    dependencies = [
        ("posthog", "1411_personalapikey_expires_at"),
        ("canvas", "0003_migrate_desktop_tree"),
    ]

    operations = [
        SafeDropTable(["posthog_filesystemfolderinstructions", "posthog_filesystemfoldercontextgeneration"]),
    ]
