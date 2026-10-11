from django.db import migrations

# Rows from before `last_seen_at` existed get the migration time, so a stale one becomes reapable after
# the usual window rather than holding its slot forever. A second run matches nothing.
BACKFILL_LAST_SEEN_AT = """
-- migration-analyzer: safe reason=holds only the instances the logs and insight parallel runs wrote, and nothing reads it on a request path
UPDATE alerts_platformalert SET last_seen_at = now() WHERE last_seen_at IS NULL
"""


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0012_platformalert_last_seen_at"),
    ]

    operations = [
        migrations.RunSQL(BACKFILL_LAST_SEEN_AT, reverse_sql=migrations.RunSQL.noop),
    ]
