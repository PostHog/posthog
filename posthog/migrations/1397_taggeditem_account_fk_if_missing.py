from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1396_events_retention_config"),
    ]

    operations = [
        # 1172 skips this foreign key when customer_analytics_account does not exist yet, which happens on a
        # partially migrated database. Where any foreign key on the column exists, this is a no-op.
        migrations.RunSQL(
            sql="""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint c
                        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
                        WHERE c.contype = 'f'
                            AND c.conrelid = 'posthog_taggeditem'::regclass
                            AND a.attname = 'account_id'
                    ) THEN
                        ALTER TABLE "posthog_taggeditem"
                        ADD CONSTRAINT "posthog_taggeditem_account_id_fk"
                        FOREIGN KEY ("account_id") REFERENCES "customer_analytics_account"("id")
                        DEFERRABLE INITIALLY DEFERRED NOT VALID;
                        ALTER TABLE "posthog_taggeditem" VALIDATE CONSTRAINT "posthog_taggeditem_account_id_fk";
                    END IF;
                END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
