from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0004_add_saved_query_origin"),
    ]

    operations = [
        migrations.RunSQL(
            """
        -- migration-analyzer: safe reason=Data warehouse table with limited customer usage
        UPDATE posthog_externaldataschema
        SET sync_time_of_day = null
        WHERE sync_time_of_day = '00:00:00';
    """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
