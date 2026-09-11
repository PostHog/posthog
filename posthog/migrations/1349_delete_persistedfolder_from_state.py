from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1348_drop_organization_is_hipaa_column"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # The table stays for now, so a rollback still finds it. A later migration drops it.
            state_operations=[
                migrations.DeleteModel(name="PersistedFolder"),
            ],
            database_operations=[
                # Django no longer knows the table, so it cannot include it when tests truncate
                # posthog_team and posthog_user, and Postgres refuses to truncate a table a foreign
                # key points to. Both statements are IF EXISTS, so a bin/migrate retry is a no-op.
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE posthog_persistedfolder DROP CONSTRAINT IF EXISTS posthog_persistedfolder_team_id_a8bb8f3e_fk_posthog_team_id;
                        ALTER TABLE posthog_persistedfolder DROP CONSTRAINT IF EXISTS posthog_persistedfolder_user_id_dee73fbd_fk_posthog_user_id;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
