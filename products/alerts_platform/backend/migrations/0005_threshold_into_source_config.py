from django.db import migrations

# Only the logs backfill wrote these columns, so the three of them are a logs row's whole bound.
# A row that already has a condition is left alone, which makes a retry under `bin/migrate` a no-op.
COPY_BOUND_INTO_SOURCE_CONFIG = """
-- migration-analyzer: safe reason=holds only the copies a manual logs backfill made, one row per logs alert, and nothing reads it on a request path
UPDATE alerts_platformalertconfiguration
SET source_config = source_config || jsonb_build_object(
    'condition',
    jsonb_build_object(
        'threshold_count', threshold_count,
        'threshold_operator', threshold_operator,
        'window_minutes', window_minutes
    )
)
WHERE threshold_count IS NOT NULL
  AND NOT source_config ? 'condition'
"""


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0004_threshold_fields_nullable"),
    ]

    operations = [
        migrations.RunSQL(COPY_BOUND_INTO_SOURCE_CONFIG, reverse_sql=migrations.RunSQL.noop),
    ]
