# Second step after migration 0032 removed the v1 Dataset and DatasetItem models
# from Django state. Nothing reads or writes these tables.

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
