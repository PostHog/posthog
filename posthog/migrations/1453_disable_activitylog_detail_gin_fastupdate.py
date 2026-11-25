import django.contrib.postgres.indexes
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1452_organization_external_project_link"),
    ]

    # Turning `fastupdate` off is a metadata change, so no rebuild is needed. It does not flush the
    # entries already in the pending list; the next vacuum of the table merges them.
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER INDEX IF EXISTS "idx_alog_detail_gin_path_ops" SET (fastupdate = off);',
                    reverse_sql='ALTER INDEX IF EXISTS "idx_alog_detail_gin_path_ops" SET (fastupdate = on);',
                ),
            ],
            state_operations=[
                migrations.RemoveIndex(
                    model_name="activitylog",
                    name="idx_alog_detail_gin_path_ops",
                ),
                migrations.AddIndex(
                    model_name="activitylog",
                    index=django.contrib.postgres.indexes.GinIndex(
                        fastupdate=False,
                        fields=["detail"],
                        name="idx_alog_detail_gin_path_ops",
                        opclasses=["jsonb_path_ops"],
                    ),
                ),
            ],
        ),
    ]
