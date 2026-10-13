from django.db import migrations


class Migration(migrations.Migration):
    """Drop the cimd_metadata_url column.

    1327 removed the field from Django state, so this is the database half of that drop and
    carries no state operation. Land it only once 1327 has been deployed for a full deploy
    cycle: before that, a rollback restores code that still selects the column.

    Reverse recreates the column and its indexes so rolling this one back on its own leaves a
    schema Django agrees with. The values are gone for good, which is safe because client_id
    holds the same URL for every row that had one.
    """

    dependencies = [("posthog", "1328_remove_userproductlist_reason_state")]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "posthog_oauthapplication" DROP COLUMN IF EXISTS "cimd_metadata_url"; -- drop-column-ignore',
            reverse_sql="""
            ALTER TABLE "posthog_oauthapplication" ADD COLUMN IF NOT EXISTS "cimd_metadata_url" varchar(2048) NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS "posthog_oauthapplication_cimd_metadata_url_key"
                ON "posthog_oauthapplication" ("cimd_metadata_url");
            CREATE INDEX IF NOT EXISTS "posthog_oauthapplication_cimd_metadata_url_df24bc90_like"
                ON "posthog_oauthapplication" ("cimd_metadata_url" varchar_pattern_ops);
            """,
        ),
    ]
