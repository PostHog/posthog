from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0064_alter_emailthreadaccountlink_match_source"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                # Completes 0014, which removed the field from Django state only.
                # The drop takes the column's index with it.
                migrations.RunSQL(
                    sql='ALTER TABLE "posthog_conversations_ticket" DROP COLUMN IF EXISTS "assigned_to_id"',
                    reverse_sql='ALTER TABLE "posthog_conversations_ticket" ADD COLUMN "assigned_to_id" integer NULL',
                ),
            ],
        ),
    ]
