from django.db import migrations

# A saved `order` the recordings query no longer accepts would fail validation, so dropping it falls back to the
# default order. Removing keys inside one UPDATE keeps any edit a user makes to the row while the migration runs.
DROP_RETIRED_RELEVANCE_FILTERS = """
UPDATE posthog_sessionrecordingplaylist
SET filters = CASE WHEN filters->>'order' = 'surfacing_score' THEN filters - 'order' ELSE filters END - 'recommended_only'
WHERE filters->>'order' = 'surfacing_score' OR filters ? 'recommended_only'
"""


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1435_ema_issuer_management"),
    ]

    operations = [
        migrations.RunSQL(DROP_RETIRED_RELEVANCE_FILTERS, migrations.RunSQL.noop, elidable=True),
    ]
