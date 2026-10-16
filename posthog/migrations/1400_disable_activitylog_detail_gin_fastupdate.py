import django.contrib.postgres.indexes
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1399_alter_user_ui_configuration_help_text"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                # Changing fastupdate takes ACCESS EXCLUSIVE on the index, which blocks every
                # insert into posthog_activitylog. A short wait gives up early, and bin/migrate retries.
                migrations.RunSQL(
                    sql="""
                        SET LOCAL lock_timeout = '2s';
                        ALTER INDEX IF EXISTS "idx_alog_detail_gin_path_ops" SET (fastupdate = off);
                    """,
                    reverse_sql="""
                        SET LOCAL lock_timeout = '2s';
                        ALTER INDEX IF EXISTS "idx_alog_detail_gin_path_ops" SET (fastupdate = on);
                    """,
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
