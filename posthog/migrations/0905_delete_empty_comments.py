# Generated manually to clean up empty comments

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0904_alter_dashboard_creation_mode"),
    ]

    operations = [
        migrations.RunSQL(
            """
            DELETE FROM posthog_comment
            WHERE (content = '' OR content IS NULL)
              AND rich_content = '{"type": "doc", "content": [{"type": "paragraph", "content": [{"text": "", "type": "text"}]}]}'::jsonb;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
