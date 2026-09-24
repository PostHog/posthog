from django.db import migrations

# Django named the unique_together constraint itself, and truncated the name to fit Postgres's
# identifier limit, so it is not something to retype here: a wrong guess plus IF EXISTS is a
# migration that succeeds and drops nothing. Read it out of the catalog instead.
DROP_UNIQUE_TOGETHER = """
    DO $$
    DECLARE
        constraint_name text;
    BEGIN
        SELECT con.conname INTO constraint_name
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = 'posthog_taggeditem'
          AND con.contype = 'u'
          AND array_length(con.conkey, 1) = 14;

        IF constraint_name IS NOT NULL THEN
            EXECUTE format('ALTER TABLE posthog_taggeditem DROP CONSTRAINT %I', constraint_name);
        END IF;
    END $$
"""

# `taggeditem_generic_pointer_set` keeps the pointer's own shape, so dropping this one removes
# a guard on columns nothing writes after this release, not a guard on live data.
DROP_CHECK = "ALTER TABLE posthog_taggeditem DROP CONSTRAINT IF EXISTS exactly_one_related_object"


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1377_untrack_superseded_experiment_settings"),
    ]

    # Two catalog changes, each taking ACCESS EXCLUSIVE on posthog_taggeditem for microseconds.
    # Both are idempotent, so this does nothing where an operator already dropped them.
    #
    # This runs before the concurrent index drops on purpose. DropIndexConcurrently sets
    # lock_timeout to 0 on the connection and does not put it back, so a migration after it
    # would wait for this table lock without a limit, and every query that loads a tag would
    # queue behind that wait.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterUniqueTogether(name="taggeditem", unique_together=set()),
                migrations.RemoveConstraint(model_name="taggeditem", name="exactly_one_related_object"),
            ],
            database_operations=[
                migrations.RunSQL(sql=DROP_CHECK, reverse_sql=migrations.RunSQL.noop),
                migrations.RunSQL(sql=DROP_UNIQUE_TOGETHER, reverse_sql=migrations.RunSQL.noop),
            ],
        ),
    ]
