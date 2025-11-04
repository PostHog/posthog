from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0003_backfill_partition_format"),
    ]

    operations = [
        migrations.RunSQL("""
        -- migration-analyzer: safe reason=Data warehouse table with limited customer usage
        UPDATE posthog_externaldataschema
        SET sync_time_of_day = null
        WHERE sync_time_of_day = '00:00:00';
    """)
    ]
