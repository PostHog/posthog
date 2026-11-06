from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ee", "0058_backfill_scim_provisioned_user_config")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="scimprovisioneduser",
                    constraint=models.UniqueConstraint(
                        fields=("user", "identity_provider_config"),
                        name="unique_user_identity_provider_config",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    # Promotes the index 0057 built concurrently. Postgres only updates the catalog
                    # here, so the ACCESS EXCLUSIVE lock is taken and released without any scan.
                    # Guarded so a bin/migrate retry, or a database that already carries the
                    # constraint, is a no-op rather than an error.
                    sql="""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = 'unique_user_identity_provider_config'
                              AND conrelid = 'ee_scimprovisioneduser'::regclass
                        ) THEN
                            ALTER TABLE ee_scimprovisioneduser
                            ADD CONSTRAINT unique_user_identity_provider_config
                            UNIQUE USING INDEX unique_user_identity_provider_config;
                        END IF;
                    END $$;
                    """,
                    reverse_sql=(
                        "ALTER TABLE ee_scimprovisioneduser "
                        "DROP CONSTRAINT IF EXISTS unique_user_identity_provider_config;"
                    ),
                ),
            ],
        ),
    ]
