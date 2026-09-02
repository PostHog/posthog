from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0036_dataset_item_client_id_and_version_dataset"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                -- migration-analyzer: safe reason=This table has no production writers before this migration
                UPDATE llm_analytics_datasetitemversion_v2 AS version
                SET dataset_id = item.dataset_id
                FROM llm_analytics_datasetitem_v2 AS item
                WHERE version.dataset_item_id = item.id
                  AND version.dataset_id IS NULL
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
