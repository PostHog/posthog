# Phase 2 of the staged drop. Migration 0032 (#75748, on master since 2026-08-03) removed the v1
# Dataset and DatasetItem models from Django state and moved the live models to the _v2 tables.
# Nothing has read or written the v1 tables since.
#
# Migration 0032 copied no v1 rows into the _v2 tables, so this drop destroys whatever the v1 tables
# still hold. The reverse is a no-op, because a CREATE TABLE would only fake a recovery.
#
# Drop the item table first, because the v1 child still holds a foreign key to the v1 parent.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0042_aiobservabilitychecklistitemstate"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS llm_analytics_datasetitem;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS llm_analytics_dataset;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
