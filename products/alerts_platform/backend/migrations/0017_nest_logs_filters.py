from django.db import migrations

# A logs copy kept its filters at the top level beside `condition`. The live read rewrites an
# enabled copy at its next check, but a disabled or switched-off copy is never checked, so this
# moves every row. A row that already has `filters` is left alone, which makes a retry under
# `bin/migrate` a no-op.
NEST_LOGS_FILTERS = """
-- migration-analyzer: safe reason=one row per logs alert copy, and the live read rewrites the same rows in the same shape
UPDATE alerts_platformalertconfiguration
SET source_config = jsonb_build_object('filters', source_config - 'condition')
    || CASE
        WHEN source_config ? 'condition' THEN jsonb_build_object('condition', source_config -> 'condition')
        ELSE '{}'::jsonb
    END
WHERE source_kind = 'logs'
  AND jsonb_typeof(source_config) = 'object'
  AND NOT source_config ? 'filters'
"""


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0016_platformalertdeliverypath"),
    ]

    operations = [
        migrations.RunSQL(NEST_LOGS_FILTERS, reverse_sql=migrations.RunSQL.noop),
    ]
