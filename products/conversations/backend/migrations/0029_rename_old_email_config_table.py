from django.db import migrations


class Migration(migrations.Migration):
    """Drop old (empty) email config table.

    Model was removed from Django state in 0028. This drops the table
    so that 0030 can recreate it with a UUID PK and many-per-team support.

    No production data exists in this table, so a clean drop is safe.
    """

    dependencies = [
        ("conversations", "0028_remove_old_email_config"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_conversations_email_config CASCADE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
