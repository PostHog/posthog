from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0054_source_ref_unique_index"),
    ]

    operations = [
        # Django drops an unconditional UniqueConstraint with DROP CONSTRAINT, so the index built by
        # the previous migration is attached as a table constraint to match the state declared here.
        # The concurrent build leaves lock_timeout at zero for the session, so the attachment, which
        # takes a brief ACCESS EXCLUSIVE lock, restores a bound for its own transaction. The guard
        # keeps a bin/migrate retry from failing on a constraint that already exists.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="accountrelationship",
                    constraint=models.UniqueConstraint(
                        fields=("team", "source", "source_ref"),
                        name="unique_relationship_per_source_ref",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        SET LOCAL lock_timeout = '20s';
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM pg_constraint WHERE conname = 'unique_relationship_per_source_ref'
                            ) THEN
                                ALTER TABLE "customer_analytics_accountrelationship"
                                ADD CONSTRAINT "unique_relationship_per_source_ref"
                                UNIQUE USING INDEX "unique_relationship_per_source_ref"; -- existing-table-constraint-ignore
                            END IF;
                        END $$;
                    """,
                    reverse_sql="""
                        ALTER TABLE "customer_analytics_accountrelationship"
                        DROP CONSTRAINT IF EXISTS "unique_relationship_per_source_ref";
                    """,
                ),
            ],
        ),
    ]
