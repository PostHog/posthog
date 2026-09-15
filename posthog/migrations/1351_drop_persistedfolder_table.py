from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1350_alter_userscenepersonalisation_dashboard"),
    ]

    operations = [
        # 1349 removed the model from Django state and dropped the two foreign keys, so this takes
        # ACCESS EXCLUSIVE on the dead table alone. No table points at it, and the drop takes the
        # three unused indexes with it.
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_persistedfolder;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
