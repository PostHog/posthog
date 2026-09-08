from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1299_alter_identityproviderconfig_saml_relay_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="identityproviderconfig",
                    name="saml_relay_state",
                    field=models.CharField(blank=True, max_length=36, null=True, unique=True),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    # Promotes the index 1293 built concurrently. Postgres only updates the
                    # catalog here, so the ACCESS EXCLUSIVE lock is taken and released without any
                    # scan. Guarded so a bin/migrate retry, or a database that already carries the
                    # constraint, is a no-op rather than an error.
                    sql="""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = 'posthog_identityproviderconfig_saml_relay_state_a35fb61b_uniq' AND conrelid = 'posthog_identityproviderconfig'::regclass
                        ) THEN
                            ALTER TABLE posthog_identityproviderconfig
                            ADD CONSTRAINT posthog_identityproviderconfig_saml_relay_state_a35fb61b_uniq
                            UNIQUE USING INDEX posthog_identityproviderconfig_saml_relay_state_a35fb61b_uniq;
                        END IF;
                    END $$;
                    """,
                    reverse_sql="ALTER TABLE posthog_identityproviderconfig DROP CONSTRAINT IF EXISTS posthog_identityproviderconfig_saml_relay_state_a35fb61b_uniq;",
                ),
            ],
        ),
    ]
