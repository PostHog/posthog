from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1200_persistedfolder_surface_unique"),
    ]

    operations = [
        # Drop the old (team, user, type) unique constraint now that the surface-aware unique index
        # from the previous migration enforces uniqueness. DROP CONSTRAINT is a fast metadata-only
        # operation (brief ACCESS EXCLUSIVE lock, no table scan), so it does not need CONCURRENTLY.
        # Django resolves the auto-generated constraint name from its own state.
        migrations.AlterUniqueTogether(
            name="persistedfolder",
            unique_together=set(),
        ),
    ]
