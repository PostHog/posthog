from django.db import migrations

# The pre-generic-relation foreign key names. The constraints below carry names this
# repository chose, so `IF EXISTS` on them cannot silently miss a differently named object.
LEGACY_FIELDS = (
    "dashboard",
    "insight",
    "event_definition",
    "property_definition",
    "action",
    "feature_flag",
    "experiment_saved_metric",
    "ticket",
    "account",
    "endpoint",
    "replay_scanner",
    "project",
    "experiment",
)

# Django named the unique_together constraint itself, and the name is truncated to fit
# Postgres's identifier limit, so it is not something to retype here: a wrong guess plus
# IF EXISTS is a migration that succeeds and drops nothing. Read it out of the catalog.
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

DROP_STATEMENTS = [
    *[f"DROP INDEX IF EXISTS unique_{field}_tagged_item" for field in LEGACY_FIELDS],
    "ALTER TABLE posthog_taggeditem DROP CONSTRAINT IF EXISTS exactly_one_related_object",
    DROP_UNIQUE_TOGETHER,
]


class Migration(migrations.Migration):
    # Every statement takes ACCESS EXCLUSIVE on posthog_taggeditem for a catalog change, and
    # a non-atomic migration gives each one its own transaction. Holding fifteen such locks to
    # the end of a single transaction is what stalls reads on the table.
    atomic = False

    dependencies = [
        ("posthog", "1377_untrack_superseded_experiment_settings"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterUniqueTogether(name="taggeditem", unique_together=set()),
                *[
                    migrations.RemoveConstraint(model_name="taggeditem", name=f"unique_{field}_tagged_item")
                    for field in LEGACY_FIELDS
                ],
                migrations.RemoveConstraint(model_name="taggeditem", name="exactly_one_related_object"),
            ],
            # Every statement is idempotent, so this is a no-op against a database where an
            # operator already dropped these by hand. That is how they leave the prod regions:
            # the first attempt at this change deadlocked inside bin/migrate.
            database_operations=[
                migrations.RunSQL(sql=statement, reverse_sql=migrations.RunSQL.noop) for statement in DROP_STATEMENTS
            ],
        ),
    ]
