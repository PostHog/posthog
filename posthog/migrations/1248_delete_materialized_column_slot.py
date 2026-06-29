from django.db import migrations

# State-only removal of the MaterializedColumnSlot model (the "dmat" dynamic-materialization
# feature, which is being removed). Per docs/published/handbook/engineering/safe-django-migrations.md
# (Dropping Tables), this drops the model from Django's state without dropping the table, so code
# still rolling out during the deploy can't hit a missing table. The physical DROP TABLE is a
# tracked follow-up to run after this has deployed everywhere.
#
# The table FKs to posthog_team / posthog_user / posthog_propertydefinition, which TransactionTestCase
# truncates. Once the model leaves Django's state, Django no longer truncates the slot table, so those
# inbound FK constraints would block TRUNCATE of the parents. Drop the physical FK constraints here
# (the table is going away anyway). Constraint names are DB-generated hashes, so resolve them at runtime.
DROP_FK_CONSTRAINTS = """
DO $$
DECLARE
    r record;
BEGIN
    IF to_regclass('posthog_materializedcolumnslot') IS NULL THEN
        RETURN;
    END IF;
    FOR r IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'posthog_materializedcolumnslot'::regclass AND contype = 'f'
    LOOP
        EXECUTE 'ALTER TABLE posthog_materializedcolumnslot DROP CONSTRAINT IF EXISTS ' || quote_ident(r.conname);
    END LOOP;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1247_oauthaccesstoken_token_idx"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="MaterializedColumnSlot"),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=DROP_FK_CONSTRAINTS,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
