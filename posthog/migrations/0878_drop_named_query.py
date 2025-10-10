from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0877_delete_named_query_from_state"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_namedquery;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
