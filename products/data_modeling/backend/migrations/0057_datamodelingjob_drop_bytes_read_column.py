from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0056_datamodelingjob_untrack_bytes_read"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "posthog_datamodelingjob" DROP COLUMN IF EXISTS "bytes_read"',
                    reverse_sql='ALTER TABLE "posthog_datamodelingjob" ADD COLUMN IF NOT EXISTS "bytes_read" bigint NULL',
                ),
            ],
        ),
    ]
