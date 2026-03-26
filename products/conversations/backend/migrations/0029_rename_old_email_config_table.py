from django.db import migrations


class Migration(migrations.Migration):
    """Rename old (empty) email config table out of the way.

    Model was removed from Django state in 0028. This renames the table
    so that 0030 can recreate it with a UUID PK and many-per-team support.
    """

    dependencies = [
        ("conversations", "0028_remove_old_email_config"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE IF EXISTS posthog_conversations_email_config RENAME TO posthog_conversations_email_config_old;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
