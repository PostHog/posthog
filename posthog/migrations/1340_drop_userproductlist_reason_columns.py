from django.db import migrations


class Migration(migrations.Migration):
    """Drop the `reason` / `reason_text` columns from posthog_userproductlist.

    Migration 1328 already removed them from Django's model state, so nothing reads
    or writes them any more. This is the second phase from safe-django-migrations.md
    "Dropping Columns": deploy the state removal, wait a full deploy cycle, then drop.

    `DROP COLUMN` takes a brief ACCESS EXCLUSIVE lock on posthog_userproductlist.
    That table is not on the hot-table list, and the drop is metadata-only, so the
    lock is held for microseconds once it is granted.

    Irreversible: the column data is gone. `reverse_sql` re-adds empty nullable
    columns so the migration can be unapplied, but it cannot bring the values back.
    """

    dependencies = [
        ("posthog", "1339_validate_taggeditem_project_fk"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE "posthog_userproductlist" DROP COLUMN IF EXISTS "reason";
                ALTER TABLE "posthog_userproductlist" DROP COLUMN IF EXISTS "reason_text";
            """,
            reverse_sql="""
                ALTER TABLE "posthog_userproductlist" ADD COLUMN IF NOT EXISTS "reason" varchar(32) NULL;
                ALTER TABLE "posthog_userproductlist" ADD COLUMN IF NOT EXISTS "reason_text" text NULL;
            """,
        ),
    ]
