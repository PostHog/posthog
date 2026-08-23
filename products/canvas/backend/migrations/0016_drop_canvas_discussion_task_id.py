from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0015_remove_canvas_discussion_task_id"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE posthog_canvas DROP COLUMN IF EXISTS discussion_task_id;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
