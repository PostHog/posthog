from django.db import migrations

DELETE_FILE_SYSTEM_ROWS = """
DELETE FROM posthog_filesystem fs
USING posthog_dashboarditem i
WHERE fs.type = 'insight'
  AND fs.team_id = i.team_id
  AND fs.ref = i.short_id
  AND i.deleted = true
"""

DELETE_SHORTCUTS = """
DELETE FROM posthog_filesystemshortcut s
USING posthog_dashboarditem i
WHERE s.type = 'insight'
  AND s.team_id = i.team_id
  AND s.ref = i.short_id
  AND i.deleted = true
"""


class Migration(migrations.Migration):
    dependencies = [("posthog", "1413_event_filter_pipeline_override")]

    operations = [
        migrations.RunSQL(DELETE_FILE_SYSTEM_ROWS, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(DELETE_SHORTCUTS, reverse_sql=migrations.RunSQL.noop),
    ]
