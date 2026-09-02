from django.db import migrations


class Migration(migrations.Migration):
    # Each DROP CONSTRAINT takes ACCESS EXCLUSIVE on the *referenced* parent as well as on the dead
    # table, so one transaction would hold the posthog_team lock for up to lock_timeout while it waits
    # for posthog_user, queueing every query on posthog_team behind it. Separate transactions release
    # each parent immediately. Both statements are IF EXISTS, so a bin/migrate retry is a no-op.
    atomic = False

    dependencies = [
        ("posthog", "1333_uploaded_media_library_index"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # The table itself stays, so a rollback still finds it. A later migration drops it.
            state_operations=[
                migrations.DeleteModel(
                    name="PersistedFolder",
                ),
            ],
            database_operations=[
                # Django no longer knows the table, so it cannot include it when tests truncate
                # posthog_team and posthog_user, and Postgres refuses to truncate a table a foreign
                # key points to.
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "posthog_persistedfolder" DROP CONSTRAINT IF EXISTS '
                        '"posthog_persistedfolder_team_id_a8bb8f3e_fk_posthog_team_id";'
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "posthog_persistedfolder" DROP CONSTRAINT IF EXISTS '
                        '"posthog_persistedfolder_user_id_dee73fbd_fk_posthog_user_id";'
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
