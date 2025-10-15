from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0880_datawarehousetable_queryable_folder"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_namedquery;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
