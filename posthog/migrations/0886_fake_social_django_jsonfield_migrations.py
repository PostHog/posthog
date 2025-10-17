# Generated manually for social-auth-app-django upgrade

from django.db import migrations


def mark_social_django_migrations_applied(apps, schema_editor):
    """
    Mark social_django migrations 0011-0016 as applied without running them.

    Background:
    - PostHog has had SOCIAL_AUTH_JSONFIELD_ENABLED=True since 2022
    - This caused social_django to use PostgreSQL jsonb for extra_data/data fields
    - Production database already has: jsonb columns + bigint IDs
    - Migrations 0011-0016 try to migrate TextField→JSONField but columns are already jsonb
    - Running these migrations would:
      - 0012: Add redundant extra_data_new/data_new columns
      - 0013: Copy data unnecessarily
      - 0014: DROP the working extra_data/data columns (DANGEROUS!)
      - 0015: RENAME extra_data_new→extra_data (would fail, breaks rollback)

    Solution:
    - Mark 0011-0016 as applied without executing them
    - Database already matches target state
    - Upgrading from social-auth-app-django 5.0.0 to 5.4.0+

    See: https://github.com/python-social-auth/social-app-django/commit/6ee061b
    """
    from django.db.migrations.recorder import MigrationRecorder

    recorder = MigrationRecorder(schema_editor.connection)

    migrations_to_fake = [
        ("social_django", "0011_alter_id_fields"),
        ("social_django", "0012_usersocialauth_extra_data_new"),
        ("social_django", "0013_migrate_extra_data"),
        ("social_django", "0014_remove_usersocialauth_extra_data"),
        ("social_django", "0015_rename_extra_data_new_usersocialauth_extra_data"),
        ("social_django", "0016_alter_usersocialauth_extra_data"),
    ]

    for app_label, name in migrations_to_fake:
        # Only mark as applied if not already recorded
        if not recorder.migration_qs.filter(app=app_label, name=name).exists():
            recorder.record_applied(app_label, name)


def unmark_social_django_migrations(apps, schema_editor):
    """
    Reverse operation: remove migration records.

    WARNING: This doesn't undo any schema changes, just removes the records.
    Only use if you need to re-run the actual migrations.
    """
    from django.db.migrations.recorder import MigrationRecorder

    recorder = MigrationRecorder(schema_editor.connection)
    recorder.migration_qs.filter(
        app="social_django",
        name__in=[
            "0011_alter_id_fields",
            "0012_usersocialauth_extra_data_new",
            "0013_migrate_extra_data",
            "0014_remove_usersocialauth_extra_data",
            "0015_rename_extra_data_new_usersocialauth_extra_data",
            "0016_alter_usersocialauth_extra_data",
        ],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0885_migrate_notebooks_models"),
        # Ensure social_django 0010 is applied before we mark 0011-0016
        ("social_django", "0010_uid_db_index"),
    ]

    operations = [
        migrations.RunPython(
            mark_social_django_migrations_applied,
            reverse_code=unmark_social_django_migrations,
        ),
    ]
