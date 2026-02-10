from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("social_django", "0016_alter_usersocialauth_extra_data"),
        ("posthog", "1000_create_healthissue_table"),
    ]

    operations = [
        # Remove the unique_together (provider, uid) constraint so that
        # one GitHub/Google account can be linked to multiple PostHog users.
        migrations.RunSQL(
            sql="ALTER TABLE social_auth_usersocialauth DROP CONSTRAINT IF EXISTS social_auth_usersocialauth_provider_uid_e6b5e668_uniq",
            reverse_sql="ALTER TABLE social_auth_usersocialauth ADD CONSTRAINT social_auth_usersocialauth_provider_uid_e6b5e668_uniq UNIQUE (provider, uid)",
        ),
        # Add a composite index on (provider, uid) for query performance since we removed the unique constraint
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS social_auth_usersocialauth_provider_uid_idx ON social_auth_usersocialauth (provider, uid)",
            reverse_sql="DROP INDEX IF EXISTS social_auth_usersocialauth_provider_uid_idx",
        ),
        # Add unique constraint on (provider, uid, user_id) to prevent the same user
        # from linking the same social account twice
        migrations.RunSQL(
            sql="CREATE UNIQUE INDEX IF NOT EXISTS social_auth_usersocialauth_provider_uid_user_uniq ON social_auth_usersocialauth (provider, uid, user_id)",
            reverse_sql="DROP INDEX IF EXISTS social_auth_usersocialauth_provider_uid_user_uniq",
        ),
    ]
