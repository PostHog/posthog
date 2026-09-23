from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0017_squash_2026_09_07_finalize_fks"),
    ]

    # State-only removal: the column stays in place until a follow-up migration
    # drops it after a full deploy cycle (see safe-django-migrations.md). The
    # column is NOT NULL with no database default, so it gets one here; without
    # it every insert that no longer names the column fails.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="canvas",
                    name="context",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE posthog_canvas ALTER COLUMN context SET DEFAULT '';",
                    reverse_sql="ALTER TABLE posthog_canvas ALTER COLUMN context DROP DEFAULT;",
                ),
            ],
        ),
    ]
