from django.db import migrations


class Migration(migrations.Migration):
    # Follow-up to the state-only removal in 0015. Runs after a full deploy cycle,
    # once no code references this column. IF EXISTS keeps it idempotent under
    # bin/migrate retries.
    dependencies = [
        ("canvas", "0015_remove_canvas_discussion_task_id"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE posthog_canvas DROP COLUMN IF EXISTS discussion_task_id;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
