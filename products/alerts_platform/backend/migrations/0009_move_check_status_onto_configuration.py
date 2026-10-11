from django.db import migrations

# Every instance written so far has the empty grouping key, so its ERRORED or BROKEN is the whole
# configuration's. Both statements match nothing on a second run, which makes a retry a no-op.
COPY_STATUS_ONTO_CONFIGURATION = """
-- migration-analyzer: safe reason=holds only the copies the logs and insight backfills made, and nothing reads it on a request path
UPDATE alerts_platformalertconfiguration AS configuration
SET check_status = alert.state
FROM alerts_platformalert AS alert
WHERE alert.configuration_id = configuration.id
  AND alert.grouping_key = ''
  AND alert.state IN ('errored', 'broken')
"""

# The machine already ended the firing when it wrote ERRORED or BROKEN, so the instance is not firing.
CLEAR_STATUS_FROM_INSTANCES = """
-- migration-analyzer: safe reason=holds only the copies the logs and insight backfills made, and nothing reads it on a request path
UPDATE alerts_platformalert
SET state = 'not_firing', firing_started_at = NULL
WHERE state IN ('errored', 'broken')
"""


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0008_platformalertconfiguration_check_status"),
    ]

    operations = [
        migrations.RunSQL(COPY_STATUS_ONTO_CONFIGURATION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(CLEAR_STATUS_FROM_INSTANCES, reverse_sql=migrations.RunSQL.noop),
    ]
