from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0879_migrate_error_tracking_models"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_namedquery;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
