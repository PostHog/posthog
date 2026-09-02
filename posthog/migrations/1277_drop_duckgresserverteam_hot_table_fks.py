from django.db import migrations

DROP_RETAINED_TABLE_HOT_FKS = """
DO $$
DECLARE
    constraint_name text;
BEGIN
    FOR constraint_name IN
        SELECT DISTINCT constraint_record.conname
        FROM pg_constraint AS constraint_record
        JOIN pg_class AS table_record ON table_record.oid = constraint_record.conrelid
        JOIN LATERAL unnest(constraint_record.conkey) AS key_column(attnum) ON TRUE
        JOIN pg_attribute AS column_record
            ON column_record.attrelid = table_record.oid
            AND column_record.attnum = key_column.attnum
        WHERE table_record.relname = 'posthog_duckgresserverteam'
            AND table_record.relnamespace = current_schema()::regnamespace
            AND constraint_record.contype = 'f'
            AND column_record.attname IN ('team_id', 'created_by_id')
    LOOP
        EXECUTE format(
            'ALTER TABLE posthog_duckgresserverteam DROP CONSTRAINT IF EXISTS %I',
            constraint_name
        );
    END LOOP;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("posthog", "1276_untrack_legacy_provisioning_columns")]

    operations = [
        migrations.RunSQL(
            sql=DROP_RETAINED_TABLE_HOT_FKS,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
