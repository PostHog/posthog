from django.db import migrations


class Migration(migrations.Migration):
    """Rename old (empty) email config table out of the way.

    Model was removed from Django state in 0028. This renames the table
    so that 0030 can recreate it with a UUID PK and many-per-team support.

    We also drop orphaned indexes because PostgreSQL does not rename
    indexes when a table is renamed — they would collide with the
    indexes Django creates for the new table in 0030.
    """

    dependencies = [
        ("conversations", "0028_remove_old_email_config"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE IF EXISTS posthog_conversations_email_config
                    RENAME TO posthog_conversations_email_config_old;
                DROP INDEX IF EXISTS posthog_conversations_email_config_inbound_token_d60f0422_like;
                DROP INDEX IF EXISTS posthog_conversations_email_config_inbound_token_d60f0422_uniq;
                DROP INDEX IF EXISTS posthog_conversations_email_config_inbound_token_key;
                DROP INDEX IF EXISTS unique_email_domain;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
