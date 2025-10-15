from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0882_add_team_default_evaluation_tags"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_namedquery;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
