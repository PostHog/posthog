from django.db import migrations

# A backfill copied each source's snooze onto the instance with the empty grouping key, and a
# source snooze mutes the whole alert. Both statements match nothing on a second run.
COPY_SNOOZE_ONTO_CONFIGURATION = """
-- migration-analyzer: safe reason=holds only the copies the logs and insight backfills made, and nothing reads it on a request path
UPDATE alerts_platformalertconfiguration AS configuration
SET snooze_until = alert.snooze_until
FROM alerts_platformalert AS alert
WHERE alert.configuration_id = configuration.id
  AND alert.grouping_key = ''
  AND alert.snooze_until IS NOT NULL
  AND configuration.snooze_until IS NULL
"""

CLEAR_SNOOZE_FROM_INSTANCES = """
-- migration-analyzer: safe reason=holds only the copies the logs and insight backfills made, and nothing reads it on a request path
UPDATE alerts_platformalert
SET snooze_until = NULL
WHERE grouping_key = ''
  AND snooze_until IS NOT NULL
"""


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0010_platformalertconfiguration_grouping_snooze"),
    ]

    operations = [
        migrations.RunSQL(COPY_SNOOZE_ONTO_CONFIGURATION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(CLEAR_SNOOZE_FROM_INSTANCES, reverse_sql=migrations.RunSQL.noop),
    ]
