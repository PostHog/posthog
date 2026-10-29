from django.db import migrations

# A metrics alert created before its destinations moved to `AlertDestination` rows kept source ownership,
# and could then never take a destination. No metrics alert had a destination of its own to move. A
# second run matches nothing.
MOVE_METRICS_DESTINATIONS = """
-- migration-analyzer: safe reason=matches only metrics alert configurations, which a rollout flag limits to one project
UPDATE alerts_platformalertconfiguration SET destinations_owner = 'platform'
WHERE source_kind = 'metrics' AND destinations_owner = 'source'
"""


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0021_rule_labels_and_annotations"),
    ]

    operations = [
        migrations.RunSQL(MOVE_METRICS_DESTINATIONS, reverse_sql=migrations.RunSQL.noop),
    ]
